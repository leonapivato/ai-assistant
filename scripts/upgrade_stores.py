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
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from pydantic import BaseModel

from ai_assistant.app.composition import (
    PERSON_MODEL_FILENAME,
    PROFILE_FIELD_CHARS,
    telegram_intake_path,
)
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.types import (
    MAX_STORY_PAGE,
    OWNER_PERSON_ID,
    ActionRequest,
    ActivationEffect,
    ActivationUnderstanding,
    ApprovalCard,
    ApprovalGiver,
    ApprovalOutcomePush,
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalStepAnswer,
    ApprovalTap,
    ApprovalWriteAnswer,
    Attestation,
    CandidateDecline,
    ChannelContext,
    ChannelIdentity,
    ChatDevice,
    ControllerRule,
    ControllerStage,
    CostBasis,
    DataTier,
    DeviceAccess,
    DeviceRole,
    DueAfterTasks,
    DueAt,
    DueNow,
    DueOnRule,
    EpisodeProcessingRecord,
    EpisodicMemory,
    EvaluationTrace,
    FindingAnnotations,
    GrantScope,
    Idempotency,
    InputPart,
    JoinedInput,
    Memory,
    MemoryMark,
    MemoryOperation,
    MemoryOperationKind,
    MemorySource,
    MemorySupport,
    MemoryWriterName,
    MessageAuthor,
    NewMessage,
    NotificationCandidate,
    ObservationAttempt,
    ObservationAttemptEnd,
    ObservationFinding,
    ObservationRecord,
    ObservationState,
    ObservationWrite,
    ObserverCall,
    ObserverStep,
    OccurrencePush,
    OccurrenceState,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    PersonActHow,
    PersonModelAct,
    PinPart,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingReason,
    ProcessingStatus,
    ProfileField,
    ProposedNarrowing,
    ProposedSuggestion,
    Provenance,
    ProvisioningState,
    QuestionPart,
    ReadingCertainty,
    ReadOutcome,
    RecordedChannelTrigger,
    RecordedInputMessage,
    RecordedTextInput,
    RememberCallPart,
    RequestedCall,
    Reversibility,
    RiskLevel,
    RuleDay,
    RulePush,
    ScheduledTaskAuthor,
    SecretName,
    SecretScope,
    SituationLabel,
    SourceGrant,
    SourceReadRecord,
    StageEntry,
    StageOutcome,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StorySummaryDraft,
    StorySummaryLine,
    SuggestionKind,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    TaskRuleKind,
    TaskSpawn,
    TaskWriteAnswer,
    TelegramOutcome,
    TicketClaim,
    ToolCost,
    ToolDefinition,
    ToolOutcome,
    TraceKind,
    TraceOutcome,
    UnderstandingOmission,
    UnderstandingProducer,
    rests_on_recorded_external_content,
    stamped_support,
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
from ai_assistant.memory._legacy import LEGACY_KINDS, LEGACY_NOTE, legacy_wording
from ai_assistant.memory.conversation_store import SqliteConversationStore
from ai_assistant.memory.person_model_store import SqlitePersonModelStore
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
    line's intake record, the booking provider's store and the person-model store. The
    hashing embedder keeps the check offline and quick; the memory store's schema and its
    upgrades are the same code whichever embedder fills the vectors.

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
        person_model=True,
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


#: The channel the activation episode was on, so its channel number is read back.
_CHANNEL: Final = ChannelIdentity(channel_type="conversation", instance_id="upgrade-chat")


def _activation_episode(moment: Moment) -> EpisodicMemory:
    """An ended activation's episode, with its processing record (ADR-0275)."""
    channel = _CHANNEL
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
                parties=(SupportHolder.person(OWNER_PERSON_ID),),
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=ended_pass(ended),
        ),
    )


#: The line a taken-over activation ran on, so a joined input names another place.
_LINE: Final = ChannelIdentity(channel_type="telegram", instance_id="upgrade-line")

#: The owner, whose words every message the check records carries (ADR-0351 §3:2).
_OWNER: Final = SupportHolder.person(OWNER_PERSON_ID)


def _stage(stage: ControllerStage, due: ControllerRule, at: datetime) -> StageEntry:
    return StageEntry(stage=stage, due=due, started_at=at, ended_at=at, outcome=StageOutcome.DONE)


def _joined_episode(moment: Moment) -> EpisodicMemory:
    """An ended activation that took a join on its place and a takeover (ADR-0332 §3, §4).

    Its processing record carries ``joined``, an understanding version that
    ``continues`` another activation, and the takeover's stage and rule, so a later
    build's upgrade check reads back each shape ADR-0332 §7 adds to the record; and, as
    ADR-0349 §10:2 and §10:7 shape them, a version continuing two activations and two
    inputs taken from one activation side by side.
    """
    started, ended = moment.ago(minutes=9), moment.ago(minutes=8)
    joined_at = moment.ago(minutes=8, seconds=50)

    def understood(version: int, *, continues: tuple[str, ...] = ()) -> ActivationUnderstanding:
        return ActivationUnderstanding(
            version=version,
            recorded_at=joined_at,
            producer=UnderstandingProducer.INTERPRETATION,
            meaning="Book Riverside for Saturday, for four.",
            continues=continues,
        )

    return EpisodicMemory(
        id="mem-episode-joined",
        content="The user booked Riverside for Saturday, for four.",
        provenance=_provenance(moment),
        occurred_at=ended,
        processing_record=EpisodeProcessingRecord(
            activation_id="act-upgrade-2",
            started_at=started,
            ended_at=ended,
            trigger=RecordedChannelTrigger(
                target=_CHANNEL,
                channel=_CHANNEL,
                payload=RecordedTextInput(text="Book Riverside for Friday"),
                context=ChannelContext(),
                reply=None,
                parties=(SupportHolder.person(OWNER_PERSON_ID),),
            ),
            status=ProcessingStatus.COMPLETED,
            reason=ProcessingReason.RETURNED,
            understanding=(
                understood(1),
                understood(2, continues=("act-upgrade-line",)),
                understood(3, continues=("act-upgrade-line", "act-upgrade-web")),
            ),
            stages=(
                _stage(ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD, started),
                _stage(ControllerStage.TAKEOVER, ControllerRule.TAKEOVER_UNDECIDED, joined_at),
                _stage(ControllerStage.UNDERSTANDING, ControllerRule.NOT_UNDERSTOOD, joined_at),
                _stage(ControllerStage.END, ControllerRule.NOTHING_DUE, ended),
            ),
            joined=(
                JoinedInput(
                    joined_at=joined_at,
                    channel=_CHANNEL,
                    messages=(
                        RecordedInputMessage(
                            text="Actually, Saturday", sent_at=joined_at, party=_OWNER
                        ),
                    ),
                ),
                JoinedInput(
                    joined_at=joined_at,
                    channel=_LINE,
                    messages=(
                        RecordedInputMessage(
                            text="for four", sent_at=joined_at, position=12, party=_OWNER
                        ),
                    ),
                    taken_over_from="act-upgrade-line",
                ),
                # ADR-0349 §7:7: an absorbed activation brings every input it holds, each
                # naming it, so this one's second input stands beside its first.
                JoinedInput(
                    joined_at=joined_at,
                    channel=_CHANNEL,
                    messages=(
                        RecordedInputMessage(text="at seven", sent_at=joined_at, party=_OWNER),
                    ),
                    taken_over_from="act-upgrade-line",
                ),
            ),
        ),
    )


def _taken_over_episode(moment: Moment) -> EpisodicMemory:
    """An activation whose input was taken, frozen naming its taker (ADR-0352 §5:2, §6:5).

    It froze *stopped*, its end entry the stop's, carrying ``taken_over_by``: the joined
    episode's activation, which took its matter. A new record of its own, read back keyed
    by its id, so no read-back shape moves and the memory store owes no carry: a base
    that predates it reads back no such key, as #3440's records were added.
    """
    started, ended = moment.ago(minutes=9, seconds=30), moment.ago(minutes=8, seconds=50)
    return EpisodicMemory(
        id="mem-episode-taken-over",
        content="The user asked for Saturday, which the booking took in.",
        provenance=_provenance(moment),
        occurred_at=ended,
        processing_record=EpisodeProcessingRecord(
            activation_id="act-upgrade-taken",
            started_at=started,
            ended_at=ended,
            trigger=RecordedChannelTrigger(
                target=_CHANNEL,
                channel=_CHANNEL,
                payload=RecordedTextInput(text="Actually, Saturday"),
                context=ChannelContext(),
                reply=None,
                parties=(SupportHolder.person(OWNER_PERSON_ID),),
            ),
            status=ProcessingStatus.INTERRUPTED,
            reason=ProcessingReason.STOPPED,
            understanding_omitted=UnderstandingOmission.NOT_REACHED,
            stages=(_stage(ControllerStage.END, ControllerRule.STOPPED, ended),),
            taken_over_by="act-upgrade-2",
        ),
    )


def _support(
    part: InputPart | RememberCallPart, origin: SupportOrigin, moment: Moment
) -> MemorySupport:
    """One support for a memory the check writes, added by ``remember`` (ADR-0328 §4).

    It carries the holder ADR-0345 §2's table gives it, as a writer records one, so a
    later build's upgrade check reads holders back.
    """
    return stamped_support(
        MemorySupport(
            points_at=part,
            origin=origin,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            when=moment.ago(minutes=20),
            added_at=moment.ago(minutes=19),
            added_by=MemoryWriterName.REMEMBER,
        ),
        None,
    )


def _memory_record(
    record_id: str, content: str, support: MemorySupport, **envelope: object
) -> Memory:
    """A memory resting on ``support``, created citing it (ADR-0328 §3, §5)."""
    return Memory.model_validate(
        {
            **envelope,
            "id": record_id,
            "content": content,
            "supports": (support,),
            "operations": (
                MemoryOperation(
                    kind=MemoryOperationKind.CREATE,
                    cites=support.points_at,
                    at=support.added_at,
                    by=support.added_by,
                ),
            ),
        }
    )


def _pinned_memory(episode: EpisodicMemory, moment: Moment) -> Memory:
    """A memory the user said and then pinned, so a later base writes a pin's support.

    The pin's support (ADR-0338 §4:4) is ``for``, backs the memory as worded, is
    ``sure``, is dated at the pin's instant and was added by the observer (§4:6), so a
    later build's upgrade check reads back the ``pin`` part and the ``pinned`` origin.
    """
    said = _support(InputPart(episode=episode.id), SupportOrigin.USER_MESSAGE, moment)
    pinned = stamped_support(
        MemorySupport(
            points_at=PinPart(pin="pin-upgrade"),
            origin=SupportOrigin.PINNED,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            how_sure=ReadingCertainty.SURE,
            when=moment.ago(minutes=12),
            added_at=moment.ago(minutes=11),
            added_by=MemoryWriterName.OBSERVER,
        ),
        None,
    )
    created = _memory_record("mem-pinned", "The user is vegetarian.", said)
    return Memory.model_validate(
        created.model_dump()
        | {
            "supports": (said, pinned),
            "operations": (
                *created.operations,
                MemoryOperation(
                    kind=MemoryOperationKind.ADD_SUPPORT,
                    cites=pinned.points_at,
                    at=pinned.added_at,
                    by=MemoryWriterName.OBSERVER,
                ),
            ),
        }
    )


async def _write_memory(directory: Path, moment: Moment) -> None:
    traces = _traces(directory)
    store = _memory(directory, traces)
    episode = _activation_episode(moment)
    try:
        await store.add(
            _memory_record(
                "mem-said",
                "The user's sister is called Ada.",
                _support(InputPart(episode=episode.id), SupportOrigin.USER_MESSAGE, moment),
                # ADR-0345 §7, §8, §9: a label, a mark and the people a memory is about,
                # so a later build's upgrade check reads each back.
                subjects=("Ada",),
                involved=(OWNER_PERSON_ID,),
                labels=(
                    SituationLabel(
                        text="family",
                        added_at=moment.ago(minutes=18),
                        added_by=MemoryWriterName.OBSERVER,
                        episode=episode.id,
                    ),
                ),
                marks=(MemoryMark.OCCASION,),
            )
        )
        await store.add(
            _memory_record(
                "mem-remembered",
                "The user prefers mornings for appointments.",
                _support(
                    RememberCallPart(episode=episode.id, effect="effect-upgrade"),
                    SupportOrigin.REMEMBERED,
                    moment,
                ),
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
        await store.add(episode)
        await store.add(_joined_episode(moment))
        await store.add(_taken_over_episode(moment))
        await store.add(_pinned_memory(episode, moment))
        chunk = await store.walk_records(_WALK, limit=2)
        if chunk.position is not None:
            await store.advance_walk(_WALK, position=chunk.position)
    finally:
        store.close()
        traces.close()


def _validity_end(record: Mapping[str, Json]) -> str | None:
    """The validity end a record read back carries, as read, or ``None`` where it is open."""
    validity = record.get("validity")
    end = validity.get("valid_until") if isinstance(validity, dict) else None
    return end if isinstance(end, str) else None


def _memory_record_carry(records: Records) -> Records:
    """What a memory store read back before ADR-0328 reads back after it (§16).

    Each semantic, preference or procedural record becomes a memory at its id: its
    wording by §16:3, its envelope fields unchanged (§16:2), one legacy support that
    points at it and carries it whole (§16:4), and a create by ``migration`` at its
    ``last_updated`` (§16:6), followed by an end at its validity end where that had
    already passed, as the head's upgrade, run before this carry, also found. The
    support's ``added_at`` and ``when`` are the upgrade's instant and the cited
    episodes', which this carry leaves to the comparison, which lets the head read back
    more than is said here. The support's ``carries`` is the
    record as stored, which the read-back shows less of than the stored blob holds
    (its ``revision`` is the row's), so the carry names the record's id, kind and
    content in it. Every episode, the walk and the nearest hits are unchanged: a
    record's vector embeds its ``content``, and the records this check writes are worded
    as they were stored.
    """
    carried: Records = {}
    for key, value in records.items():
        if not key.startswith("record/") or not isinstance(value, dict):
            carried[key] = value
            continue
        kind = value.get("kind")
        if kind not in LEGACY_KINDS:
            carried[key] = value
            continue
        provenance = value.get("provenance")
        if not isinstance(provenance, dict):
            carried[key] = value
            continue
        # The core predicate over the validated provenance, as the head's upgrade reads
        # it (§16:4): a user's own assertion never rests on external content, whatever
        # its `derived_from_external` says (ADR-0106 §2's band guard).
        outside = rests_on_recorded_external_content(Provenance.model_validate(provenance))
        part: Json = {"part": "legacy", "record": value["id"]}
        support: dict[str, Json] = {
            "points_at": part,
            "origin": "legacy_outside" if outside else "legacy",
            "direction": "for",
            "note": LEGACY_NOTE,
            "backs_as_worded": True,
            "source_details": provenance.get("attestation"),
            "added_by": "migration",
            "carries": {"id": value["id"], "kind": kind, "content": value["content"]},
        }
        memory: dict[str, Json] = {
            name: value[name]
            for name in ("id", "validity", "expires_at", "about_person", "topics", "placement")
            if name in value
        }
        operations: list[Json] = [
            {
                "kind": "create",
                "cites": part,
                "note": LEGACY_NOTE,
                "at": provenance.get("last_updated"),
                "by": "migration",
            }
        ]
        end = _validity_end(value)
        if end is not None and datetime.fromisoformat(end) <= datetime.now(UTC):
            operations.append({"kind": "end", "cites": part, "at": end})
        memory |= {
            "kind": "memory",
            "content": legacy_wording(value),
            "supports": [support],
            "operations": operations,
            "status": "current" if len(operations) == 1 else "ended",
        }
        carried[key] = memory
    return carried


def _memory_placed_carry(records: Records) -> Records:
    """What a memory store read back before ADR-0345 reads back after it (§13).

    Each memory's ``about_person`` becomes ``subjects`` holding that one name, or
    ``None`` where it named none, and ``involved`` is ``None`` (§13:1); each of its
    topics becomes a label added by ``migration`` and suggested by no episode (§10:2),
    whose instant is the head's upgrade's, which this carry leaves to the comparison; and
    it gains no mark. Each support gains its holder, which the head reads back beside
    what is said here. Every episode, the walk and the nearest hits are unchanged.
    """
    carried: Records = {}
    for key, value in records.items():
        if not key.startswith("record/") or not isinstance(value, dict):
            carried[key] = value
            continue
        if value.get("kind") != "memory":
            carried[key] = value
            continue
        memory = dict(value)
        about = memory.pop("about_person", None)
        topics = memory.pop("topics", None)
        memory["subjects"] = None if about is None else [about]
        memory["involved"] = None
        memory["labels"] = [
            {"text": topic, "added_by": "migration", "episode": None}
            for topic in (topics if isinstance(topics, list) else [])
        ]
        memory["marks"] = []
        carried[key] = memory
    return carried


def _memory_continuing_carry(records: Records) -> Records:
    """What a memory store read back before ADR-0349 reads back after it (§10:6).

    Each episode's understanding versions read back ``continues`` as a sequence: one
    that named an activation as a one-element sequence of it, and one that named none as
    an empty sequence. Nothing else in the episode, no memory, the walk and the nearest
    hits move: an episode's search text, which its vector embeds, is not its
    understanding's ``continues``.
    """
    carried: Records = {}
    for key, value in records.items():
        processing = value.get("processing_record") if isinstance(value, dict) else None
        versions = processing.get("understanding") if isinstance(processing, dict) else None
        if not isinstance(value, dict) or not isinstance(versions, list):
            carried[key] = value
            continue
        understanding: list[Json] = []
        for version in versions:
            if isinstance(version, dict) and "continues" in version:
                held = version["continues"]
                named: Json = [] if held is None else [held] if isinstance(held, str) else held
                version = version | {"continues": named}  # noqa: PLW2901 — the carried version
            understanding.append(version)
        assert isinstance(processing, dict)  # noqa: S101  # read above, with its versions
        carried[key] = value | {"processing_record": processing | {"understanding": understanding}}
    return carried


def _memory_parties_carry(records: Records) -> Records:
    """What a memory store read back before ADR-0351 reads back after it (§9).

    Each episode's trigger reads back no ``origin``, which ADR-0351 §10:2 computes from
    the parties and stores nowhere; what it gains, ``parties``, each message's ``party``
    and each version's and joined input's ``relayed``, the comparison admits as added.
    Nothing else moves: no memory, no support (§9:4), the walk and the nearest hits,
    since an episode's search text, which its vector embeds, reads what the parties give,
    which is the origin it was recorded under.
    """
    carried: Records = {}
    for key, value in records.items():
        processing = value.get("processing_record") if isinstance(value, dict) else None
        trigger = processing.get("trigger") if isinstance(processing, dict) else None
        if not isinstance(trigger, dict) or "origin" not in trigger:
            carried[key] = value
            continue
        assert isinstance(value, dict)  # noqa: S101  # read above, with its trigger
        assert isinstance(processing, dict)  # noqa: S101  # read above, with its trigger
        kept = {name: one for name, one in trigger.items() if name != "origin"}
        carried[key] = value | {"processing_record": processing | {"trigger": kept}}
    return carried


#: ADR-0353 §9:5's retired fields, which the head's upgrade drops from every version.
_RETIRED_UNDERSTANDING: Final = (
    "meaning_ground",
    "references",
    "relationships",
    "unresolved",
    "answers",
)


def _memory_understood_carry(records: Records) -> Records:
    """What a memory store read back before ADR-0353 reads back after it (§9:6).

    Each episode's understanding versions read back without their retired fields, by
    the owner's ruling under ADR-0326 §4:4: the ground, the references, the
    relationships, the unresolved matters and the answer pointers. The referents of a
    version's references and relationships read back in its ``meaning_referents``, after
    its meaning's own, each added once and none it already holds; what each version
    gains, ``unclear``, the comparison admits as added. Nothing else moves: no memory,
    the walk and the nearest hits, since an episode's vector embeds its ``content``.
    """
    carried: Records = {}
    for key, value in records.items():
        processing = value.get("processing_record") if isinstance(value, dict) else None
        versions = processing.get("understanding") if isinstance(processing, dict) else None
        if not isinstance(value, dict) or not isinstance(versions, list):
            carried[key] = value
            continue
        understanding: list[Json] = []
        for version in versions:
            if not isinstance(version, dict):
                understanding.append(version)
                continue
            own = version.get("meaning_referents")
            kept: list[Json] = list(own) if isinstance(own, list) else []
            seen = [json.dumps(one, sort_keys=True) for one in kept]
            for name in ("references", "relationships"):
                held = version.get(name)
                for one in held if isinstance(held, list) else []:
                    referents = one.get("referents") if isinstance(one, dict) else None
                    for referent in referents if isinstance(referents, list) else []:
                        if (text := json.dumps(referent, sort_keys=True)) not in seen:
                            seen.append(text)
                            kept.append(referent)
            reshaped = {
                name: one for name, one in version.items() if name not in _RETIRED_UNDERSTANDING
            }
            understanding.append(reshaped | {"meaning_referents": kept})
        assert isinstance(processing, dict)  # noqa: S101  # read above, with its versions
        carried[key] = value | {"processing_record": processing | {"understanding": understanding}}
    return carried


def _memory_called_carry(records: Records) -> Records:
    """What a memory store read back before ADR-0356 reads back after it (§13:5).

    Each episode's processing record reads back at ``schema_version`` 12, every stored
    field whole; what it gains, ``call_records``, empty on every record the base wrote,
    the comparison admits as added. Nothing else moves: no memory, the walk and the
    nearest hits.
    """
    carried: Records = {}
    for key, value in records.items():
        processing = value.get("processing_record") if isinstance(value, dict) else None
        if not isinstance(value, dict) or not isinstance(processing, dict):
            carried[key] = value
            continue
        carried[key] = value | {"processing_record": processing | {"schema_version": 12}}
    return carried


async def _read_memory(directory: Path) -> Records:
    """Every record, the walk's resumption, and the nearest record to each one's content.

    The records alone would miss an upgrade that kept every row and lost the vector
    index ``search`` reads, or attached its vectors to the wrong rows. So each record is
    searched for by its own content, and the nearest hit is read back: the hashing
    embedder maps that text onto the record's own vector, so where the vectors are
    whole and in place, every record is its own nearest.
    """
    traces = _traces(directory)
    store = _memory(directory, traces)
    try:
        exported = await store.export()
        records = _keyed("record", exported, _field("id"))
        rest = await store.walk_records(_WALK, limit=_PAGE)
        records["walk"] = [record.id for record in rest.records]
        records["channel"] = to_json(await store.channel_episode_ids(_CHANNEL, limit=_PAGE))
        for record in exported:
            if record.content:
                found = await store.search(record.content, limit=1)
                records[f"nearest/{record.id}"] = [hit.id for hit in found.records]
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
        # Two summaries, so the first is one a later write replaced, which this build
        # keeps (ADR-0347 §2) and a later build's upgrade check reads back.
        for lines, outside in (
            (("The dentist appointment.",), True),
            (("The dentist appointment, now Thursday.",), False),
        ):
            state = await store.current_summary(story)
            assert state is not None  # noqa: S101  # the story was just made
            await store.write_summary(
                story,
                StorySummaryDraft(
                    lines=tuple(StorySummaryLine(text=text) for text in lines), outside=outside
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
    """Every story's records, each version's kept summary, and the store's position.

    ``kept/<story>`` is the summary each version of the story's log wrote, as
    :meth:`~ai_assistant.core.protocols.StoryStore.summary_at` reads it, ``None`` where
    the store holds no text for it (ADR-0347 §2:4); ``position`` is where the store's
    one sequence stands (§2:5). Both are read from shape 2.
    """
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
            versions = await store.summary_versions(story, limit=MAX_STORY_PAGE)
            records[f"summaries/{story}"] = to_json(versions)
            records[f"summary/{story}"] = to_json(await store.current_summary(story))
            records[f"kept/{story}"] = [
                {
                    "version": one.version,
                    "summary": to_json(await store.summary_at(story, one.version)),
                }
                for one in (() if versions is None else versions.versions)
            ]
        records["position"] = await store.position()
        return records
    finally:
        store.close()


def _stories_kept_carry(records: Records) -> Records:
    """ADR-0347 §5:1: what the head's upgrade of a shape-1 story store reads back.

    The base kept each story's current summary alone, and the head's upgrade keeps it
    as the text of the version that wrote it, no earlier version gaining any: so each
    story's ``kept`` names every version its log holds, with the story's current
    summary at the version that wrote it and ``None`` at every other. The position is
    the counter the base's summary reads reported as their ``as_of``, which the upgrade
    leaves where it stood; with no story, nothing was ever written on it.

    Raises:
        TypeError: If a story's summary or version records are not what a shape-1
            read-back holds.
    """
    carried = dict(records)
    position: Json = 0
    for key, value in records.items():
        if not key.startswith("summary/"):
            continue
        story = key.removeprefix("summary/")
        versions = records.get(f"summaries/{story}")
        if not isinstance(value, dict) or not isinstance(versions, dict):
            msg = f"a shape-1 story read-back holds no summary and version log for {story}"
            raise TypeError(msg)
        current = value.get("summary")
        logged = versions.get("versions")
        if not isinstance(logged, list) or not (current is None or isinstance(current, dict)):
            msg = f"a shape-1 story read-back's summary records for {story} are not records"
            raise TypeError(msg)
        numbers = [one.get("version") if isinstance(one, dict) else None for one in logged]
        carried[f"kept/{story}"] = [
            {
                "version": number,
                "summary": (
                    current if current is not None and number == current.get("version") else None
                ),
            }
            for number in numbers
        ]
        position = value.get("as_of")
    carried["position"] = position
    return carried


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
        # ADR-0329 §16: an episode the observer attempted, which waits for a retry.
        await store.write_observation(
            ObservationRecord(
                episode="activation:act-upgrade-1",
                state=ObservationState.WAITING,
                attempts=(
                    ObservationAttempt(
                        started_at=moment.ago(minutes=10),
                        calls=(ObserverCall(step=ObserverStep.SCOUT, at=moment.ago(minutes=10)),),
                        end=ObservationAttemptEnd.FAILED,
                    ),
                ),
                next_attempt_at=moment.ago(minutes=5),
                findings=(
                    ObservationFinding(
                        id="finding-upgrade-1",
                        episode="activation:act-upgrade-1",
                        claim="The user prefers window seats.",
                        rests_on=(InputPart(episode="activation:act-upgrade-1"),),
                    ),
                    # §12:6, §16:4: a finding whose commit failed part-way, carrying the
                    # supply's placement meet and what the commit wrote before failing.
                    ObservationFinding(
                        id="finding-upgrade-2",
                        episode="activation:act-upgrade-1",
                        claim="The user's sister is called Ada.",
                        rests_on=(InputPart(episode="activation:act-upgrade-1", message=0),),
                        supply=Placement(
                            reach=PlacementReach.OWNER,
                            set_by=PlacementSetter.DERIVED,
                            set_at=moment.ago(minutes=10),
                        ),
                        written=(
                            ObservationWrite(
                                memory="memory-upgrade-ada",
                                operations=(MemoryOperationKind.CREATE,),
                            ),
                        ),
                    ),
                    # ADR-0346 §4:5: a finding carrying the scout's annotations.
                    ObservationFinding(
                        id="finding-upgrade-3",
                        episode="activation:act-upgrade-1",
                        claim="Ada is the user's younger sister.",
                        rests_on=(InputPart(episode="activation:act-upgrade-1", message=0),),
                        annotations=FindingAnnotations(
                            subjects=("Ada", OWNER_PERSON_ID),
                            why="The user mentions Ada often.",
                            situations=("planning a family visit",),
                            narrowing=ProposedNarrowing(
                                reach=PlacementReach.OWNER, note="Family matters."
                            ),
                        ),
                    ),
                ),
                # ADR-0346 §4:6: a candidate the scout declined, with its reason.
                declines=(
                    CandidateDecline(
                        candidate="effect-upgrade-1", reason="A booking detail, not worth keeping."
                    ),
                ),
            ),
            expected_revision=0,
        )
        await _write_scheduled_tasks(store, moment)
        await _write_approval_requests(store, moment)
    finally:
        store.close()


#: The activation that spawns every scheduled task below, which holds no stop record.
_SPAWNER: Final = "act-upgrade-spawner"

#: The limits the tasks below are written under: ADR-0350 §12:5's defaults.
_CHAIN_LIMIT: Final = 10
_PENDING_LIMIT: Final = 50


async def _spawned(store: SqlitePlanStore, spawn: TaskSpawn, digest: str, moment: Moment) -> None:
    """Write ``spawn`` as :data:`_SPAWNER`'s call to the spawn capability (ADR-0350 §3:3).

    Raises:
        RuntimeError: If the store does not write it, which is the writer's own failure.
    """
    written = await store.write_scheduled_task(
        spawn,
        ActivationEffect(
            id=f"effect-{spawn.id}",
            activation_id=_SPAWNER,
            round="r1",
            capability="spawn",
            values_digest=digest * 64,
            decision_id=f"d-{spawn.id}",
            claimed_at=moment.ago(minutes=13),
        ),
        match=None,
        chain_limit=_CHAIN_LIMIT,
        pending_limit=_PENDING_LIMIT,
    )
    if written.answer is not TaskWriteAnswer.WRITTEN:
        msg = f"the plan store did not write {spawn.id}: {written!r}"
        raise RuntimeError(msg)


def _task_spawn(task_id: str, moment: Moment, **parts: object) -> TaskSpawn:
    """A spawn for the owner, set in the check's conversation, as the actuator states it."""
    return TaskSpawn.model_validate(
        {
            "id": task_id,
            "person": OWNER_PERSON_ID,
            "author": ScheduledTaskAuthor.ASSISTANT,
            "when": DueNow(),
            "instruction": f"Do the step {task_id}.",
            "set_in": _CHANNEL,
            "set_at": moment.ago(minutes=13),
            **parts,
        }
    )


async def _write_scheduled_tasks(store: SqlitePlanStore, moment: Moment) -> None:
    """ADR-0350 §12:3, ADR-0340 §9: a task of each when, through each state.

    Every instant is handed in, as a caller computes it: the store computes none
    (ADR-0340 §9:5), so a rule's instants need not fall on its days to be stored.

    Raises:
        RuntimeError: If the store does not write a task or push an occurrence.
    """
    # A one-off task due now, suggesting the line, pushed and settled done (§7:5-§7:6).
    await _spawned(
        store,
        _task_spawn("task-upgrade-now", moment, places=(_LINE,), outside_content=True),
        "b",
        moment,
    )
    pushes = [await store.mark_occurrence_pushed("task-upgrade-now", 1, "act-upgrade-task-1")]
    await store.settle_occurrence("act-upgrade-task-1", OccurrenceState.DONE)
    # A one-off task due at an instant, still pending; and one waiting on it (§5:2, §5:4),
    # pending with no instant due.
    await _spawned(
        store,
        _task_spawn("task-upgrade-at", moment, when=DueAt(at=moment.now + timedelta(days=1))),
        "c",
        moment,
    )
    await _spawned(
        store,
        _task_spawn("task-upgrade-after", moment, when=DueAfterTasks(tasks=("task-upgrade-at",))),
        "d",
        moment,
    )
    # ADR-0340 §4: a task the person set on a weekly rule, missed twice and pushed late:
    # its first occurrence and the one between skipped, the latest pushed, and its
    # successor written pending, all in the push's one step (§4:6, §4:8, §9:3).
    await _spawned(
        store,
        _task_spawn(
            "task-upgrade-rule",
            moment,
            author=ScheduledTaskAuthor.PERSON,
            when=DueOnRule(
                repeats=TaskRuleKind.WEEKLY,
                days=(RuleDay.TUESDAY, RuleDay.THURSDAY),
                time_of_day=time(9, 30),
                zone="America/New_York",
                from_date=date(2026, 1, 5),
                until_date=date(2099, 12, 31),
            ),
            first_due_at=moment.ago(days=3),
        ),
        "e",
        moment,
    )
    pushes.append(
        await store.mark_occurrence_pushed(
            "task-upgrade-rule",
            1,
            "act-upgrade-task-2",
            rule=RulePush(
                skipped=(moment.ago(days=2),),
                latest=moment.ago(days=1),
                successor=moment.now + timedelta(days=1),
            ),
        )
    )
    if any(push is not OccurrencePush.PUSHED for push in pushes):
        msg = f"the plan store did not push every occurrence: {pushes!r}"
        raise RuntimeError(msg)


async def _write_approval_requests(store: SqlitePlanStore, moment: Moment) -> None:
    """ADR-0361 §8:2: a request waiting, and one approved by a tap on its card.

    The approved one carries its card and token, its ticket spent by the call it holds,
    and its outcome marked pushed, so a later head reads back each part a request holds.

    Raises:
        RuntimeError: If the store does not write a request or take a step on it.
    """
    for request_id, hotel in (("q-upgrade-waiting", "the Savoy"), ("q-upgrade-approved", "Ritz")):
        request = ApprovalRequest(
            id=request_id,
            person=OWNER_PERSON_ID,
            activation_id="act-upgrade-asking",
            round="r1",
            call=RequestedCall(tool=_tool(), values={"hotel": hotel}),
            why=f"You asked me to book {hotel}.",
            written_at=moment.ago(minutes=12),
            expires_at=moment.ago(minutes=12) + timedelta(hours=24),
        )
        written = await store.write_approval_request(
            request,
            ActivationEffect(
                id=f"effect-{request_id}",
                activation_id="act-upgrade-asking",
                round="r1",
                capability="request_approval",
                values_digest=("f" if hotel == "Ritz" else "e") * 64,
                decision_id=f"d-{request_id}",
                claimed_at=moment.ago(minutes=12),
                request=request_id,
            ),
            match=None,
        )
        if written.answer is not ApprovalWriteAnswer.WRITTEN:
            msg = f"the plan store did not write {request_id}: {written!r}"
            raise RuntimeError(msg)
    await store.record_approval_card(
        "q-upgrade-approved", ApprovalCard(place=_LINE, position=7, token=_UPGRADE_CARD)
    )
    tap = ApprovalTap(who=ApprovalGiver.USER_TAP_ON_TELEGRAM_CARD, at=moment.ago(minutes=11))
    steps = [
        (
            await store.answer_approval_request(
                "q-upgrade-approved", ApprovalRequestState.APPROVED, tap
            )
        ).answer
        is ApprovalStepAnswer.CHANGED,
        await store.mark_approval_outcome_pushed("q-upgrade-approved", "act-upgrade-approval")
        is ApprovalOutcomePush.PUSHED,
        await store.claim_ticket_call(
            ActivationEffect(
                id="effect-upgrade-ticket",
                activation_id="act-upgrade-approval",
                round="r1",
                capability="send_email",
                values_digest="d" * 64,
                decision_id="d-upgrade-ticket",
                claimed_at=moment.ago(minutes=10),
                ticket="q-upgrade-approved",
            ),
            match=None,
        )
        is TicketClaim.CLAIMED,
    ]
    if not all(steps):
        msg = f"the plan store did not take every step on the approved request: {steps!r}"
        raise RuntimeError(msg)


#: The opaque token minted for the approved request's card (ADR-0361 §4:10).
_UPGRADE_CARD: Final = "upgrade-card-1"


async def _read_plans(directory: Path) -> Records:
    store = _plans(directory)
    try:
        exported = await store.export()
        return {
            "stopped": to_json(exported.stopped_activations),
            **_keyed("effect", exported.activation_effects, _field("id")),
            "observations": to_json(exported.observations),
            # ADR-0350 §12:3: keyed, so a base that predates them reads back no key and
            # the head reads back none either; the shape does not move.
            **_keyed("task", exported.scheduled_tasks, _field("id")),
            # ADR-0361 §8:2: keyed, as the tasks are, so the shape does not move.
            **_keyed("approval", exported.approval_requests, _field("id")),
        }
    finally:
        store.close()


def _plans_cascade_carry(records: Records) -> Records:
    """What a plan store read back before ADR-0352 reads back after it (§2:6, §6:3-§6:4).

    The upgrade from label 17 applies each cascade record's reach once and drops it, and
    the export no longer carries ``cascades``, so no ``cascade/`` key is read back. The
    base's writer names its one cascade record for an activation outside every lineage,
    so the upgrade cancels no occurrence and writes no stop record, and every other
    record reads back as it was. Were a base's cascade record to reach a task, the head
    would read that task back changed and a stop record added, which this carry does not
    say, so the check would fail rather than pass it unread.
    """
    return {key: value for key, value in records.items() if not key.startswith("cascade/")}


def _plans_observations_carry(records: Records) -> Records:
    """What a plan store read back before ADR-0329 reads back after it (§16:10).

    The upgrade from label 12 adds the observation table, empty, and changes no stop or
    effect record, so a file the base wrote reads back as it did, with no observation
    record beside it.
    """
    return {**records, "observations": []}


def _plans_finding_carry(records: Records) -> Records:
    """What a plan store read back before #3205 reads back after it (ADR-0329 §16:1).

    The upgrade from label 13 rewrites no row: every finding a record holds reads back
    as it was, with ``supply`` and ``written`` empty, since nothing was recorded of
    either before the fields existed. Saying so here, rather than leaning on the
    comparison letting the head read back more, holds the head to reading them back
    *empty* and not to whatever it might invent.
    """
    observations = records.get("observations")
    if not isinstance(observations, list):
        return records
    return {**records, "observations": [_with_empty_carry(one) for one in observations]}


def _with_empty_carry(record: Json) -> Json:
    """One observation record's read-back, each finding given the empty new fields."""
    if not isinstance(record, dict) or not isinstance(record.get("findings"), list):
        return record
    findings = cast("list[Json]", record["findings"])
    return {
        **record,
        "findings": [
            {**one, "supply": None, "written": []} if isinstance(one, dict) else one
            for one in findings
        ],
    }


def _plans_annotation_carry(records: Records) -> Records:
    """What a plan store read back before ADR-0346 reads back after it (§4:5, §4:6).

    The upgrade from label 14 rewrites no row: every record reads back as it was, with
    no ``declines``, each finding with no ``annotations``, no ``further_candidates`` and
    nothing ``framed``,
    and each outcome with no
    ``unclear`` and nothing ``asked``, since nothing was recorded of any before the
    fields existed. Said here, as the carry from 13 says its own, so the head is held
    to reading them back empty.
    """
    observations = records.get("observations")
    if not isinstance(observations, list):
        return records
    return {**records, "observations": [_with_no_annotations(one) for one in observations]}


def _with_no_annotations(record: Json) -> Json:
    """One observation record's read-back, given ADR-0346's fields empty."""
    if not isinstance(record, dict):
        return record
    findings = record.get("findings")
    return {
        **record,
        "declines": [],
        "findings": [_finding_with_no_annotations(one) for one in findings]
        if isinstance(findings, list)
        else findings,
    }


def _finding_with_no_annotations(finding: Json) -> Json:
    """One finding's read-back, with no annotations and its outcome's new fields empty."""
    if not isinstance(finding, dict):
        return finding
    outcome = finding.get("outcome")
    if isinstance(outcome, dict):
        outcome = {**outcome, "unclear": [], "asked": []}
    return {
        **finding,
        "annotations": None,
        "further_candidates": [],
        "framed": [],
        "outcome": outcome,
    }


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
        records["changes"] = to_json(await store.changes(after=0, limit=_PAGE))
        records["changes/phone"] = to_json(
            await store.device_changes("phone", after=0, limit=_PAGE)
        )
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


# --- person_model.db ------------------------------------------------------------------


def _person_model(directory: Path) -> SqlitePersonModelStore:
    return SqlitePersonModelStore(
        path=directory / PERSON_MODEL_FILENAME, field_chars=PROFILE_FIELD_CHARS
    )


async def _write_person_model(directory: Path, moment: Moment) -> None:
    del moment  # the store stamps its own instants
    panel = PersonModelAct(how=PersonActHow.PANEL, by=OWNER_PERSON_ID)
    by_a_yes = PersonModelAct(
        how=PersonActHow.APPROVAL,
        by=OWNER_PERSON_ID,
        approval=QuestionPart(round="round-upgrade-1", part=1),
        episode_id="act-upgrade-1",
    )
    field = ProposedSuggestion(
        kind=SuggestionKind.FIELD,
        field=ProfileField.ADDRESS,
        value="Robin",
        episode_id="act-upgrade-1",
        part=InputPart(episode="act-upgrade-1"),
        origin=SupportOrigin.USER_MESSAGE,
    )
    store = _person_model(directory)
    try:
        owner = OWNER_PERSON_ID
        await store.set_field(owner, ProfileField.NAME, "Robin Vale", act=panel)
        await store.set_field(owner, ProfileField.TIME_ZONE, "Europe/Lisbon", act=by_a_yes)
        await store.set_field(owner, ProfileField.LANGUAGE, "Português", act=panel)
        removed = await store.add_pin(owner, "mem-upgrade-1", act=panel)
        if removed.record_id is not None:
            await store.remove_pin(owner, removed.record_id)
        await store.add_pin(owner, "mem-upgrade-2", act=by_a_yes)
        await store.add_style_mark(owner, "mem-upgrade-3")
        unmarked = await store.add_style_mark(owner, "mem-upgrade-4")
        if unmarked.record_id is not None:
            await store.remove_style_mark(owner, unmarked.record_id)
        await store.record_suggestion(owner, field)
        dismissed = await store.record_suggestion(
            owner,
            ProposedSuggestion(
                kind=SuggestionKind.PIN, memory_id="mem-upgrade-3", episode_id="act-upgrade-1"
            ),
        )
        if dismissed.record_id is not None:
            await store.dismiss_suggestion(owner, dismissed.record_id)
        accepted = await store.record_suggestion(
            owner,
            ProposedSuggestion(
                kind=SuggestionKind.PIN, memory_id="mem-upgrade-5", episode_id="act-upgrade-1"
            ),
        )
        if accepted.record_id is not None:
            await store.accept_suggestion(owner, accepted.record_id, by=owner)
    finally:
        store.close()


async def _read_person_model(directory: Path) -> Records:
    store = _person_model(directory)
    try:
        exported = to_json(await store.export())
        assert isinstance(exported, dict)  # noqa: S101  # a model dumps to an object
        return {f"export/{name}": value for name, value in exported.items()}
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
        records["verifiers"] = to_json(store.live_verifiers())
        return records
    finally:
        store.close()


#: Every store a person's hub keeps, in the order the writer fills them.
STORES: Final[tuple[Store, ...]] = (
    Store("traces", ("traces.db",), _write_traces, _read_traces),
    Store(
        "memory",
        ("memory.db",),
        _write_memory,
        _read_memory,
        shape=7,
        carries={
            1: _memory_record_carry,
            2: _memory_placed_carry,
            3: _memory_continuing_carry,
            4: _memory_parties_carry,
            5: _memory_understood_carry,
            6: _memory_called_carry,
        },
    ),
    Store(
        "stories",
        ("stories.db",),
        _write_stories,
        _read_stories,
        shape=2,
        carries={1: _stories_kept_carry},
    ),
    Store("audit", ("audit.db",), _write_audit, _read_audit),
    Store(
        "plans",
        ("plans.db",),
        _write_plans,
        _read_plans,
        shape=5,
        carries={
            1: _plans_observations_carry,
            2: _plans_finding_carry,
            3: _plans_annotation_carry,
            4: _plans_cascade_carry,
        },
    ),
    Store("conversations", ("conversations.db",), _write_conversations, _read_conversations),
    Store("grants", ("grants.db",), _write_grants, _read_grants),
    Store("reads", ("reads.db",), _write_reads, _read_reads),
    Store("notifications", ("notifications.db",), _write_notifications, _read_notifications),
    Store("outbox", ("outbox.db",), _write_outbox, _read_outbox),
    Store("connections", ("connections.db",), _write_connections, _read_connections),
    Store("telegram", ("telegram-*.db",), _write_telegram, _read_telegram),
    Store("bookings", ("bookings.db",), _write_bookings, _read_bookings),
    Store("person_model", (PERSON_MODEL_FILENAME,), _write_person_model, _read_person_model),
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

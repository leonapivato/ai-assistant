"""The conversation lifecycle stage: every sequence that spans both durable stores.

ADR-0074 §9's coordinator ruling in one object, as ADR-0283 partially supersedes
it. A conversation's history, membership and deletion are the episodes on its
channel (``ChannelIdentity("conversation", <id>)``), which the ``MemoryStore``
holds; the ``ConversationStore`` holds the conversation and two small facts about
it, its delivery rows and the observer's watermark. A ``ConversationStore`` asked
whether a conversation still has live episodes would have to reach into memory and
break golden rule 1, so this stage — the one place that legitimately holds both
handles by injection — owns the cross-store sequences:

* **history** (ADR-0283 §4, §10; ADR-0284 §6:2) — every live episode of the
  conversation in number order within the replay bound, each paired with its
  delivery row;
* **resume association** (§5) — a binding resolved through the episode that parked
  it;
* **deletion** (§8, as ADR-0293 §2:3 partially supersedes it) — stamp, which
  deletes the transcript, drop the conversation's parked reads and the record
  conditionally, and **destroy no episode**: deleting a conversation forgets
  nothing;
* **forgetting** (ADR-0293 §2:4-§2:8) — destroy every episode the conversation's
  channel holds, open ones told first, and leave the conversation and its
  transcript;
* **the chat space** (ADR-0293 §2-§5, §8) — the acts in the medium and their reads,
  relayed to the store, and the current state, read from the episodes;
* **retention reclaim** (§8) — which **destroys nothing**: it only asks whether the
  channel still holds an episode, and drops a conversation record that holds none.

Capture itself is the :class:`~ai_assistant.orchestration.activation_writer.ActivationWriter`'s
(ADR-0283 §7), which this stage builds over the same two stores.

**Neither sweep destroys an episode.** Finishing a user deletion removes the
conversation and its transcript, and forgetting is the command that reaches the
episodes (ADR-0293 §2:3, §2:4). Retention reclaim destroys nothing, because episodes
leave on their own ``expires_at``, stamped at capture from the horizon in force when
they were written.

Nothing concrete is imported: both stores arrive by injection and are seen only
through their Protocols (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelIdentity,
    ChatChanges,
    ConversationDigest,
    ConversationStartedChange,
    ConversationState,
    DevicesChangedChange,
    EpisodicMemory,
    MemoryKind,
    MessageAddedChange,
    MessageAuthor,
    ProcessingStatus,
    TranscriptMessage,
    TranscriptPage,
)
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.payloads import canonical_payload, check_payload

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        ParkedReads,
    )
    from ai_assistant.core.types import (
        ChatDevice,
        Conversation,
        MemoryRecord,
        MessageReceipt,
        ParkedBinding,
        SpokenDelivery,
        SpokenDeliveryReport,
        UserMessage,
    )

_log = structlog.get_logger(__name__)

#: The confidence every captured episode carries (ADR-0074 §4). A **documented
#: constant, strictly below 1.0**, and not a computed score — capture has nothing
#: to compute from. High, because that an exchange occurred is not in doubt; below
#: 1.0, because confidence is *standing* rather than certainty and 1.0 is the
#: standing only the user's own word carries (ADR-0072 §3). An episode rendered
#: beside an assertion at equal confidence would teach exactly the false model
#: ADR-0072 §6 exists to prevent. Nothing reads it comparatively: retrieval is
#: confidence-neutral (ADR-0072 §5) and inspection only renders it.
CAPTURE_CONFIDENCE = 0.9

#: The kinds a turn's *relevance* retrieval selects (ADR-0074 §6): the belief
#: kinds, and never ``EPISODIC``. Capture puts tens of records a day into a store
#: whose retrieval is otherwise kind-blind, so without this the first capture lane
#: would silently change what every turn retrieves — a captured turn competing
#: with beliefs for the retrieval budget — as a side effect nobody ratified.
#: Cross-conversation episodic recall is a real capability and is deferred with
#: its ranking question (§11).
BELIEF_KINDS: tuple[MemoryKind, ...] = (
    MemoryKind.SEMANTIC,
    MemoryKind.PREFERENCE,
    MemoryKind.PROCEDURAL,
)

#: How many conversations the retention reclaim shortlists per ``recent`` page.
_RECLAIM_PAGE = 50

#: The replay bound: how many of a conversation's most recent episodes
#: :meth:`ConversationLifecycle.history` reads (ADR-0283 §4:1). The value the turn
#: index's configured replay window had (ADR-0074 §9.3) — finite, and the same for
#: every caller, because an unbounded replay of a months-old conversation is a
#: prompt nobody sized.
HISTORY_REPLAY_BOUND: Final = 20

#: How many identifiers one ``channel_episode_ids`` page asks for while forgetting or
#: a reclaim walks a conversation's channel (ADR-0283 §8). The read's own bound.
_CHANNEL_PAGE: Final = 1000

#: How many open episodes one page of the current state's walk reads (ADR-0293 §8:2).
_OPEN_PAGE: Final = 100


def conversation_channel(conversation_id: str) -> ChannelIdentity:
    """The channel a conversation's episodes are written on (ADR-0275 §4:5, ADR-0283 §4)."""
    return ChannelIdentity(channel_type="conversation", instance_id=conversation_id)


def _utcnow() -> datetime:
    return datetime.now(UTC)


#: How the last activation started from a conversation ended, read off its episode's
#: status (ADR-0293 §8:3). An activation that answered, asked a question (ADR-0295 §1:
#: "an activation that asked the user a question has ended") or heard no words is done;
#: one that failed could not finish; one cut short — a restart's close among them
#: (ADR-0286 §7) — was interrupted.
_ENDINGS: Final[dict[ProcessingStatus, ActivationEnding]] = {
    ProcessingStatus.COMPLETED: ActivationEnding.DONE,
    ProcessingStatus.WAITING: ActivationEnding.DONE,
    ProcessingStatus.FAILED: ActivationEnding.COULDNT_FINISH,
    ProcessingStatus.INTERRUPTED: ActivationEnding.INTERRUPTED,
}


def activation_ending(episode: EpisodicMemory) -> ActivationEnding | None:
    """How the activation an ended episode records ended, or ``None`` for an open one.

    Shared by the engine and the canonical fake engine, so both read the current
    state's ending off the same episode the same way (ADR-0293 §8:3).
    """
    record = episode.processing_record
    if record is None or record.status is None:
        return None
    return _ENDINGS[record.status]


def started_from(record: MemoryRecord, channel: ChannelIdentity) -> EpisodicMemory | None:
    """``record`` as an episode of an activation started from ``channel``, or ``None``.

    An ended episode is on its channel (ADR-0283 §1). **An open one may not be yet**:
    a conversational pass names the conversation its episode is written for once the
    conversation is resolved (ADR-0275 §4:5 as ADR-0283 reads it), so until then its
    trigger's ``channel`` is unset and only its ``target`` names the conversation.
    Either is read here, so a running activation is found from its admission on.
    """
    if not isinstance(record, EpisodicMemory) or record.processing_record is None:
        return None
    trigger = record.processing_record.trigger
    target = getattr(trigger, "target", None)
    if trigger.channel == channel or (isinstance(target, ChannelIdentity) and target == channel):
        return record
    return None


async def _open_on(memory: MemoryStore, channel: ChannelIdentity) -> list[EpisodicMemory]:
    """Every open episode of an activation started from ``channel``, oldest first.

    The open episodes are walked whole (ADR-0286 §12:1's enumeration): they are this
    process's running activations, since a restart closes every one a dead process
    left (§7), so the walk is short.
    """
    found: list[EpisodicMemory] = []
    after: int | None = None
    while True:
        page = await memory.open_episodes(after=after, limit=_OPEN_PAGE)
        found.extend(episode for entry in page if (episode := started_from(entry.record, channel)))
        if len(page) < _OPEN_PAGE:
            return found
        after = page[-1].number


async def episodes_on_place(memory: MemoryStore, conversation_id: str) -> list[str]:
    """The id of every episode on a conversation's place, open ones first (ADR-0293 §2:4).

    What forgetting the conversation destroys, shared by the engine and the canonical
    fake engine: the running activations' open episodes, found by
    :func:`started_from` since one may not yet be on the channel (§2:6), then every
    episode ``channel_episode_ids`` holds on the channel — the enumeration of what the
    store physically holds, expired and not-yet-valid ones included (ADR-0275 §6:6) —
    whether or not the conversation still stands (§2:5). Each id once.

    Raises:
        MemoryStoreError: If the store cannot be read.
    """
    channel = conversation_channel(conversation_id)
    found = [episode.id for episode in await _open_on(memory, channel)]
    after: int | None = None
    while held := await memory.channel_episode_ids(channel, after=after, limit=_CHANNEL_PAGE):
        found.extend(one.episode_id for one in held)
        after = held[-1].number
    return list(dict.fromkeys(found))


async def conversation_state(
    memory: MemoryStore, conversation_id: str, *, running: Sequence[str | None] = ()
) -> ConversationState:
    """What a conversation's devices are shown about the assistant (ADR-0293 §8).

    **Working is the assistant's own account of what it is running** (§1:6, §8:2):
    ``running`` is the activation id of every activation this process is running
    that was started from the conversation, oldest first — ``None`` for one whose id
    the factory failed to mint, which shows "working…" with no id (ADR-0297 §5) —
    and the newest id known is the one a stop names (ADR-0295 §1:2). It is held in
    process, so an activation whose episode was forgotten or whose capture failed
    still shows, and **an open episode is never read as running**: one a failed
    capture's compensation could not delete stays open until a restart closes it
    (ADR-0286 §5), long after its activation ended.

    **How the last one ended is read from the episodes on the place**, the
    assistant's durable record of its activations, so a restart that closed an
    activation as interrupted is read back as interrupted (§9:2). Shared by the
    engine and the canonical fake engine, so both read one state the same way:

    * the place's newest **ended** episode is the last activation that ended, and its
      status says how (:func:`activation_ending`).

    An activation that wrote no episode — capture degraded, or forgotten — is not
    seen, and a conversation whose episodes were forgotten reads as idle: what the
    assistant forgot it no longer knows ran.

    Raises:
        MemoryStoreError: If the episodes cannot be read.
    """
    channel = conversation_channel(conversation_id)
    held = tuple(running)
    known = [one for one in held if one is not None]
    ended = await memory.channel_episodes(channel, limit=1)
    last = ended.entries[-1].record if ended.entries else None
    return ConversationState(
        working=bool(held),
        activation_id=known[-1] if known else None,
        last_ended=activation_ending(last) if isinstance(last, EpisodicMemory) else None,
    )


#: The widest instant and number a recorded message can carry, so the probe below
#: measures the most its record can cost rather than what it costs today.
_WIDEST_AT: Final = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
_WIDEST_NUMBER: Final = 2**63 - 1


def check_message_fits(conversation_id: str, message: UserMessage, *, max_bytes: int) -> None:
    """Refuse a message whose own record could not be read back within the limit.

    A message is accepted only where a page holding it alone — the transcript's and
    the change stream's — fits the payload limit, measured at the widest position,
    sequence number and instant it could be recorded with. Otherwise a message the
    conversation recorded would be one no read could return, and a device's cursor
    would stop at it for good: :func:`fit_transcript` and :func:`fit_changes` can
    shorten a page to one entry and no further. Shared by the engine and the
    canonical fake engine.

    Raises:
        OversizedValueError: If either one-entry page would exceed ``max_bytes``.
    """
    recorded = TranscriptMessage(
        conversation_id=conversation_id,
        position=_WIDEST_NUMBER,
        written_at=_WIDEST_AT,
        author=MessageAuthor.USER,
        text=message.text,
        # As wide as the reply the message names, and below the probe's own position,
        # which a recorded message's reference always is.
        replies_to=None
        if message.replies_to is None
        else min(message.replies_to, _WIDEST_NUMBER - 1),
        device_id=message.device_id,
        message_id=message.message_id,
    )
    check_payload(
        TranscriptPage(conversation_id=conversation_id, entries=(recorded,), as_of=_WIDEST_NUMBER),
        max_bytes=max_bytes,
        subject="the transcript page holding the message write_message() was given",
    )
    check_payload(
        ChatChanges(
            changes=(MessageAddedChange(seq=_WIDEST_NUMBER, message=recorded),),
            next_after=_WIDEST_NUMBER,
        ),
        max_bytes=max_bytes,
        subject="the change recording the message write_message() was given",
    )


#: A conversation id as wide as the store mints one (a UUID's text), for a probe that
#: measures a change about a conversation not yet started.
_PROBE_CONVERSATION: Final = "0" * 36


def check_devices_fit(
    devices: Sequence[ChatDevice], *, conversation_id: str | None, max_bytes: int
) -> None:
    """Refuse a set of devices whose own records could not be read back within the limit.

    A set of devices is recorded as a change (ADR-0293 §5:10) — "my devices" also in
    every later conversation's start — and read back on the conversation's digest
    (§3:3). A set whose one-change page or digest would exceed the payload limit
    would stop every cursor at that change, since :func:`fit_changes` can shorten a
    page to one change and no further; so it is refused before it is recorded,
    measured at the widest sequence number and instants. Shared by the engine and the
    canonical fake engine.

    Args:
        devices: The set, already checked.
        conversation_id: The conversation whose devices these are, or ``None`` for
            "my devices".
        max_bytes: The payload limit.

    Raises:
        OversizedValueError: If a record carrying the set would exceed ``max_bytes``.
    """
    held = tuple(devices)
    named = _PROBE_CONVERSATION if conversation_id is None else conversation_id
    changes: list[DevicesChangedChange | ConversationStartedChange] = [
        DevicesChangedChange(seq=_WIDEST_NUMBER, conversation_id=conversation_id, devices=held)
    ]
    if conversation_id is None:
        changes.append(
            ConversationStartedChange(seq=_WIDEST_NUMBER, conversation_id=named, devices=held)
        )
    for change in changes:
        check_payload(
            ChatChanges(changes=(change,), next_after=_WIDEST_NUMBER),
            max_bytes=max_bytes,
            subject="the change recording the devices given",
        )
    check_payload(
        ConversationDigest(
            id=named,
            started_at=_WIDEST_AT,
            last_turn_at=_WIDEST_AT,
            recorded_turns=_WIDEST_NUMBER,
            state=ConversationState(
                working=True,
                activation_id=_PROBE_CONVERSATION,
                last_ended=ActivationEnding.COULDNT_FINISH,
            ),
            devices=held,
        ),
        max_bytes=max_bytes,
        subject="the conversation read carrying the devices given",
    )


def fit_transcript(page: TranscriptPage | None, *, max_bytes: int) -> TranscriptPage | None:
    """The page shortened from its oldest end until it fits the payload limit.

    A snapshot keeps its most recent entries, and the first position left is where
    the next ``before`` reads from, so nothing is lost (ADR-0293 §5:13). Where not
    even one entry fits, the original page earns the ordinary size error.

    Raises:
        OversizedValueError: If no non-empty page fits.
    """
    if page is None or len(canonical_payload(page)) <= max_bytes:
        return page
    for start in range(1, len(page.entries)):
        fitted = page.model_copy(update={"entries": page.entries[start:]})
        if len(canonical_payload(fitted)) <= max_bytes:
            return fitted
    check_payload(page, max_bytes=max_bytes, subject="the result of transcript()")
    raise AssertionError("an oversized transcript page was unexpectedly admitted")


def fit_changes(page: ChatChanges, *, max_bytes: int) -> ChatChanges:
    """The changes shortened from their newest end until they fit the payload limit.

    ``next_after`` becomes the last change returned, so the next read resumes after
    it and nothing is lost (ADR-0293 §5:11). Where not even one change fits, the
    original page earns the ordinary size error.

    Raises:
        OversizedValueError: If no non-empty page fits.
    """
    if len(canonical_payload(page)) <= max_bytes:
        return page
    for count in range(len(page.changes) - 1, 0, -1):
        kept = page.changes[:count]
        fitted = ChatChanges(changes=kept, next_after=kept[-1].seq)
        if len(canonical_payload(fitted)) <= max_bytes:
            return fitted
    check_payload(page, max_bytes=max_bytes, subject="the result of chat_changes()")
    raise AssertionError("an oversized changes page was unexpectedly admitted")


@dataclass(frozen=True, slots=True)
class AssembledHistory:
    """A conversation's recent episodes, with their delivery facts (ADR-0283 §4, §10).

    Attributes:
        records: The channel's live episodes, oldest first in number order
            (ADR-0283 §1), within the replay bound. A deleted or expired episode is
            simply not on the channel's live read, so a conversation that lost a turn
            still resumes and never resurrects the deleted one.
        deliveries: What a device reported playing of each of those episodes, keyed
            by the episode qualified (ADR-0205 §5, ADR-0283 §10). **Every such
            episode of the tail and not only the previous one**, because a report may
            name a turn that is no longer the previous one. It is read with one
            ``deliveries`` call for the episodes this page returned, so a delivery
            fact travels with the episode it qualifies and never without it; an
            episode with no delivery row is simply absent.
        degraded: Whether reading them failed outright, which costs the turn its
            continuity exactly as a failed retrieval costs it its personalisation.
    """

    records: tuple[MemoryRecord, ...] = ()
    deliveries: Mapping[str, SpokenDelivery] = field(default_factory=dict)
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class ParkingOrigin:
    """Where a parked binding was parked: its conversation and its episode (ADR-0283 §5).

    Attributes:
        conversation_id: The conversation whose channel the parking episode is on.
        episode_id: The parking episode's id, which a resumed episode relates as its
            predecessor.
    """

    conversation_id: str
    episode_id: str


class ConversationLifecycle:
    """Owns every ``ConversationStore``/``MemoryStore`` sequence (ADR-0074 §9)."""

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        memory: MemoryStore,
        retention: timedelta | None,
        now: Clock = _utcnow,
        parked_reads: ParkedReads | None = None,
    ) -> None:
        """Wire the stage from the injected stores.

        **``retention`` must be the value ``conversations`` was built with.** No
        type can say so, so it is a composition-root obligation of the same shape
        as ADR-0028 §4's writer/store rule: this stage stamps each episode's
        ``expires_at`` from it, and the store judges a conversation record's own
        reclaim against it (ADR-0074 §7's "the horizon is read from the same
        setting the turns use — no second clock to disagree with the first"). Wired
        to two different horizons, episodes and the index that names them would
        expire on different days.

        It is a **required** keyword with no default, deliberately. ADR-0074 §7
        warns that an implementation inheriting ``confirmation_ttl``'s ``None``
        default would ship unbounded episodic retention while looking like it
        followed the ADR; a seam with no default cannot inherit one at all, and the
        one place the default is decided is ``core.config.Settings``.

        Args:
            conversations: The durable conversation index.
            memory: Long-term memory — the **same** instance the turn stage
                retrieves from and the writer persists to, because a stage wired to
                a second store would write episodes no retrieval could see and
                destroy nothing the user was shown.
            retention: The episodic horizon. ``None`` means "keep forever": no
                ``expires_at`` is stamped and the retention reclaim is switched off
                entirely rather than guessed at (ADR-0074 §7).
            now: Clock for capture stamps and the reclaim shortlist; injectable so
                tests are deterministic (CONTRIBUTING, "Determinism"). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`, so a non-conforming
                reading is this stage's own failure rather than a silently bad
                timestamp.
            parked_reads: The questions a recorded ``CONFIRM`` on a read left standing
                (ADR-0244 §3), or ``None`` where this deployment wired no such store.
                **Reached through the Protocol and never through a concrete one**
                (golden rule 1), which is why ``drop_for_conversation`` is a member of
                the contract rather than left to an implementation — and this stage is
                where it is called from, being "the one layer that legitimately holds
                both handles by injection" (ADR-0074 §9).

                **Defaulted rather than required**, which is the one departure from
                ``retention`` above and takes
                :class:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations`'
                choice for the same object one seam over. A stage with no park store
                carries §8 out exactly as it did before ADR-0244, because a deployment
                that wired none holds no park for any conversation. ``None`` drops nothing
                because there is nothing to drop.
        """
        self._conversations = conversations
        self._memory = memory
        self._retention = retention
        self._clock = checked_clock(now, owner="ConversationLifecycle")
        self._parked_reads = parked_reads
        self.activation_writer = ActivationWriter(
            conversations=conversations,
            memory=memory,
            retention=retention,
            now=now,
        )

    # --- resolving the conversation a turn runs under (§2) -------------------

    async def begin(self, conversation_id: str | None) -> Conversation:
        """Resolve the conversation this turn runs under, **before** its work (§2).

        No id starts one; an id continues that one and marks it active. Both happen
        ahead of the turn so the id exists independently of whether the turn
        succeeds — a turn that fails outright leaves an empty conversation, which
        is harmless and reclaimable — and so a continuation against a conversation
        sitting at its retention horizon is not racing the reclaim that would drop
        it. Marking activity is a separate fact from recording a turn:
        ``last_active_at`` moves, ``last_turn_at`` does not.

        Args:
            conversation_id: The conversation to continue, or ``None`` to start a
                fresh one. Untrusted input from an adapter, refused rather than
                silently started if the store does not know it (§1).

        Returns:
            The conversation the turn runs under.

        Raises:
            UnknownConversationError: If ``conversation_id`` names nothing, or
                names one the user deleted. Loud rather than silent: starting a
                fresh conversation under a new id would turn a typo or a stale
                copy-paste into "my conversation vanished".
            ConversationStoreError: If the store cannot be read or written.
        """
        if conversation_id is None:
            return await self._conversations.start()
        return await self._conversations.mark_active(conversation_id)

    async def history(self, conversation_id: str) -> AssembledHistory:
        """The conversation's recent episodes, oldest first, with their deliveries (§4).

        ADR-0283 §4:1: a ``get`` that answers nothing for a stamped or absent
        conversation, then the conversation's channel read with
        ``MemoryStore.channel_episodes`` with the replay bound as ``limit`` — and
        then, by §10, one ``deliveries`` call for the episodes it returned, each paired
        with its episode. No turn is read from the conversation store.

        **Every episode, and no eligibility** (ADR-0284 §6:2, superseding ADR-0283
        §4:1's ``episode_model_eligible=True``): a failed, interrupted or outside
        episode is part of the conversation's history like any other, and its
        renderings state its status.

        **The order is the channel's, the episodes' numbers ascending** (§1), never a
        timestamp and never an id. The read already filters by liveness, so a
        deleted, expired or never-landed episode is a gap here rather than a fault.

        Returns:
            The records and their deliveries, and whether reading them failed
            outright — which a stamped or absent conversation counts as, exactly as
            the turn index's refusal of it did.
        """
        try:
            if await self._conversations.get(conversation_id) is None:
                return AssembledHistory(degraded=True)
            page = await self._memory.channel_episodes(
                conversation_channel(conversation_id), limit=HISTORY_REPLAY_BOUND
            )
            records: list[MemoryRecord] = [entry.record for entry in page.entries]
            delivered = (
                await self._conversations.deliveries(
                    conversation_id, episode_ids=[record.id for record in records]
                )
                if records
                else {}
            )
            # ADR-0205 §5 / ADR-0283 §10: paired with the episode it qualifies, so a
            # fact whose episode is not in this page is never carried.
            deliveries: dict[str, SpokenDelivery] = {
                record.id: delivered[record.id] for record in records if record.id in delivered
            }
        except ConversationStoreError, MemoryStoreError:
            # Losing continuity costs the answer its history, not its usefulness —
            # so the turn goes on, saying so, exactly as a failed retrieval does.
            _log.warning("conversation_history_degraded", stage="history", exc_info=True)
            return AssembledHistory(degraded=True)
        return AssembledHistory(records=tuple(records), deliveries=deliveries)

    async def conversation_of_binding(self, binding: ParkedBinding) -> ParkingOrigin | None:
        """Where a parked confirmation was parked, or ``None`` (ADR-0283 §5).

        A resumption cannot be *told* which conversation it is in — the adapter
        relays an opaque token and nothing else — so the association is durable and
        recovered rather than passed: ``MemoryStore.episode_parking`` finds the
        episode whose own step parked ``binding`` (its ``links.parks``). Where that
        episode's channel is a conversation, the conversation is that channel's
        instance and the predecessor is that episode's id.

        ``None`` where no live episode parked the binding, where it is on no
        conversation's channel, and where the conversation is stamped or absent: all
        three keep ADR-0275 §6:5's degraded, no-episode behaviour, because recording
        the resumption under a fresh conversation would assert one the user never had.

        Raises:
            MemoryStoreError: If the memory store cannot be read.
            ConversationStoreError: If the conversation store cannot be read.
        """
        episode = await self._memory.episode_parking(binding)
        if episode is None or episode.processing_record is None:
            return None
        channel = episode.processing_record.trigger.channel
        if channel is None or channel.channel_type != "conversation":
            return None
        if await self._conversations.get(channel.instance_id) is None:
            return None
        return ParkingOrigin(conversation_id=channel.instance_id, episode_id=episode.id)

    async def record_delivery(self, conversation_id: str, report: SpokenDeliveryReport) -> bool:
        """Apply one device's report to the turn it names (ADR-0205 §1, §3).

        **One store call and no sequence**, which is why this is short: the store
        owns all three of §3's conditions and decides them under its own
        per-conversation exclusion, so there is nothing here to compose and nothing
        for a caller to re-derive. It sits on this stage rather than on the engine
        because this stage is where the ``ConversationStore`` handle lives.

        **A benign miss is discarded rather than raised** (§1). A report naming a
        turn this conversation does not carry — an index entry deleted or reclaimed,
        an id belonging to another conversation, a turn already stamped — performs
        nothing and returns ``False``, and the call that carried it goes on: a benign
        state must not cost the owner the turn they just spoke.

        **A store fault degrades it too, and that is this stage's judgement rather
        than a ratified clause.** ADR-0205 leaves it open; the reason to degrade is
        capture's own — the report is a fact about a turn that has already happened,
        and losing it costs a later prompt one input, where raising would throw away
        the turn the owner is speaking now. It is logged rather than swallowed.

        **An unknown conversation still raises**, because that is not a fact about
        the report at all: the same id is about to be handed to :meth:`begin`, which
        refuses it for the same reason, so answering it here would only move the
        refusal one line later.

        Args:
            conversation_id: The conversation the report is about.
            report: The device's report, naming its turn by episode id.

        Returns:
            Whether a row was stamped — the store's own answer, relayed
            (ADR-0283 §6:4) — and ``False`` where a store fault was degraded.

        Raises:
            UnknownConversationError: If the conversation is absent or stamped
                deleted.
        """
        try:
            return await self._conversations.record_delivery(
                conversation_id, episode_id=report.episode_id, delivery=report.delivery
            )
        except UnknownConversationError:
            raise
        except ConversationStoreError:
            _log.warning("spoken_delivery_unrecorded", stage="record_delivery", exc_info=True)
            return False

    # --- deletion (§8) -------------------------------------------------------

    async def digest(
        self, conversation_id: str, *, running: Sequence[str | None] = ()
    ) -> ConversationDigest | None:
        """One conversation as it is read, or ``None`` (ADR-0283 §4:2, ADR-0293 §8).

        The record for the span and ``last_turn_at``, which is the conversation's own,
        and an **unfiltered** ``channel_episodes`` read of its channel, whose ``total``
        is the count — every live episode on the channel, eligible or not, whatever
        the page held; then the conversation's devices and its current state
        (:meth:`state`).

        Returns:
            The digest, or ``None`` when the id names nothing or names a
            conversation already stamped deleted — a surface must not show, or take
            consent for, something it cannot display.

        Raises:
            ConversationStoreError: If the conversation store cannot be read.
            MemoryStoreError: If the memory store cannot be read.
        """
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            return None
        page = await self._memory.channel_episodes(conversation_channel(conversation_id), limit=1)
        devices = await self._conversations.conversation_devices(conversation_id)
        return ConversationDigest(
            id=conversation.id,
            started_at=conversation.started_at,
            last_turn_at=conversation.last_turn_at,
            recorded_turns=page.total,
            state=await self.state(conversation_id, running=running),
            devices=devices or (),
        )

    async def state(
        self, conversation_id: str, *, running: Sequence[str | None] = ()
    ) -> ConversationState:
        """What the conversation's devices are shown about the assistant (ADR-0293 §8).

        :func:`conversation_state` over this stage's memory store, with the caller's
        running activations started from the conversation.

        Raises:
            MemoryStoreError: If the episodes cannot be read.
        """
        return await conversation_state(self._memory, conversation_id, running=running)

    # --- the chat space's acts and reads (ADR-0293 §2-§5) --------------------

    async def start(self) -> Conversation:
        """Start an empty conversation, given "my devices" (ADR-0293 §2:1, §3:1)."""
        return await self._conversations.start()

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Read "my devices" (ADR-0293 §3:1)."""
        return await self._conversations.my_devices()

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices" (ADR-0293 §3:1, §3:2)."""
        return await self._conversations.set_my_devices(devices)

    async def set_conversation_devices(
        self, conversation_id: str, devices: Sequence[ChatDevice]
    ) -> bool:
        """Replace one conversation's devices (ADR-0293 §3:3)."""
        return await self._conversations.set_conversation_devices(conversation_id, devices)

    async def write(self, conversation_id: str, message: UserMessage) -> MessageReceipt:
        """Record the user's message and answer for it (ADR-0293 §4).

        The store answers *received*, a repeat, a device that is not an end for
        writing and a reply to nothing; it starts no activation, which is the
        reader's (§6).
        """
        return await self._conversations.append_message(conversation_id, message.as_new_message())

    async def delete_message(self, conversation_id: str, position: int) -> bool:
        """Delete one message, leaving its marker (ADR-0293 §5:8, §5:12)."""
        return await self._conversations.delete_message(conversation_id, position)

    async def transcript(
        self, conversation_id: str, *, before: int | None, limit: int
    ) -> TranscriptPage | None:
        """Read part of a conversation's transcript (ADR-0293 §5:13)."""
        return await self._conversations.transcript(conversation_id, before=before, limit=limit)

    async def changes(
        self, *, after: int, conversation_ids: Sequence[str] | None, limit: int
    ) -> ChatChanges:
        """Read the chat space's changes after a cursor (ADR-0293 §5:10, §5:11)."""
        return await self._conversations.changes(
            after=after, conversation_ids=conversation_ids, limit=limit
        )

    # --- forgetting (ADR-0293 §2:4-§2:8) -------------------------------------

    async def forget(self, conversation_id: str) -> bool:
        """Forget every episode on the conversation's place, and nothing else (§2:4).

        Memory's act alone: the conversation, its transcript and its devices are
        not reached (§5:6), and the place is walked whether or not the conversation
        still stands (§2:5), by :func:`episodes_on_place`. Each episode's capture in
        flight is told before its deletion, as ``forget`` tells one (ADR-0286 §8:1),
        so no later write re-creates it (§2:6). Idempotent by re-walking.

        Returns:
            Whether an episode was forgotten.

        Raises:
            MemoryStoreError: If the store cannot be read or an episode deleted.
        """
        forgot = False
        for episode_id in await episodes_on_place(self._memory, conversation_id):
            self.activation_writer.forgetting(episode_id)
            forgot = await self._memory.delete(episode_id) or forgot
        return forgot

    async def delete(self, conversation_id: str) -> bool:
        """Delete a conversation: stamp, drop its parked reads, drop the record (§8).

        ADR-0283 §8:1 as ADR-0293 §2:3 partially supersedes it: deleting removes the
        conversation and its transcript, **and none of the episodes on its place**.
        The stamp is the act in the medium — the store deletes the transcript, the
        devices and the reader's bookkeeping in the same step and records the change
        — and the record is dropped once its grace has passed. If this process dies
        between the steps the stamped record is still there, so
        :meth:`sweep_deletions` finishes it (ADR-0076).

        **The conversation's parked reads go with it** (ADR-0244 §3), through
        ``ParkedReads.drop_for_conversation`` and never through a concrete store —
        :meth:`_finish_deletion` carries the placement and its argument.

        Returns:
            ``True`` if this call stamped the conversation; ``False`` if it was
            already stamped or the id names nothing. Either way the sweep behind it
            is run, because the deletion is re-runnable.

        Raises:
            ConversationStoreError: If the store cannot be read or written.
            AssistantError: If this conversation's parked reads could not be dropped.
                The tombstone stands, and the next sweep finishes the job.
        """
        stamped = await self._conversations.stamp_deleted(conversation_id)
        try:
            await self._finish_deletion(conversation_id)
        except UnknownConversationError:
            # Someone else — another engine, or a start-up sweep — finished this one
            # between the stamp and the purge. A conversation that is gone is a
            # deletion that completed.
            _log.info("conversation_deletion_already_finished")
        return stamped

    async def sweep_deletions(self) -> int:
        """Finish every deletion a previous run left unfinished (ADR-0076).

        The start-up half of §8's reclaim. Before ADR-0076 nothing could find this
        work: the stamp hides a conversation from every presenting read, so a
        process that died between the stamp and the drop left a record that outlived
        its grace indefinitely. Since ADR-0293 §2:3 it destroys no episode, as the
        deletion it finishes destroys none.

        Walks the tombstones to an **empty batch**, because finishing one batch and
        stopping is the failure §9's own multi-batch clause forbids, and the cursor
        is placed lexically — the rows are dropped by this very sweep, so by the
        time the next batch is asked for, the id it carries names nothing.

        An id that is unknown by the time this acts on it is a **no-op and the
        sweep moves to the next**: a conversation that is gone is a deletion that
        completed (ADR-0076 §2). Every other failure aborts and propagates, because
        a sweep that swallowed real store faults to stay running would report
        success over work it never did.

        Returns:
            How many tombstones this call carried through to a drop.
        """
        dropped = 0
        cursor: str | None = None
        while True:
            batch = await self._conversations.stamped_conversation_ids(after_id=cursor)
            if not batch:
                return dropped
            for conversation_id in batch:
                try:
                    if await self._finish_deletion(conversation_id):
                        dropped += 1
                except UnknownConversationError:
                    _log.info("conversation_deletion_already_finished")
                    continue
            cursor = batch[-1]

    async def _finish_deletion(self, conversation_id: str) -> bool:
        """Destroy this conversation's parked reads, then ask for the drop (§8).

        ADR-0283 §8:1, in order, as ADR-0293 §2:3 leaves it: the parked reads' drop,
        then ``drop_if_eligible``. **No episode is destroyed**: deleting a conversation
        forgets nothing, and its episodes stay on its place until the user forgets
        them (ADR-0293 §2:4). Idempotent: a run that dies part-way is re-run from the
        beginning.

        **The parked reads go first, and the position is argued rather than free**
        (ADR-0244 §3). It is inside **step 2** and never after step 3, because
        ``drop_if_eligible`` removes the record and its tombstone — after which nothing
        enumerates this conversation again, and a park dropped there and interrupted
        would be strandable with only its own deadline to free it. That is ADR-0238 §8's
        stranding failure, the one ADR-0244 §3 contrasts a park against, and it is closed
        here by running before the drop rather than by a reconciliation walk, a tombstone
        of its own or a second lifecycle — none of which §3 admits.

        It goes **before** the episode walk, so a call arriving for a conversation
        another sweep already dropped still reaches the parks — the one route to them
        ADR-0244 §3 names besides the deadline.

        **An open park stranded by a crash anywhere in this sequence is not an
        unrecoverable orphan** (ADR-0244 §3): it carries its own ``expires_at``,
        ``outstanding`` enumerates it, and §10's expiry settles it and clears its content
        with no reference to the conversation record. A terminal one holds no content at
        all, so what is left is six scalar facts the next call removes.

        Returns:
            Whether the record was dropped. ``False`` while the grace still holds —
            the tombstone is deliberately kept alive past the deletion so a capture
            that commits and then dies is still swept.

        Raises:
            AssistantError: If the parked-read store could not be written. Nothing below
                runs and the tombstone stands: the residue of a partial failure has to be
                one the user can still reach and destroy, and a park is reachable through
                the enumeration and self-clearing on its deadline.
        """
        if self._parked_reads is not None:
            await self._parked_reads.drop_for_conversation(conversation_id)
        return await self._conversations.drop_if_eligible(conversation_id)

    # --- retention reclaim (§7) ---------------------------------------------

    async def reclaim(self) -> int:
        """Drop the index of conversations that are empty and idle (§7).

        **This sweep never destroys an episode.** Episodes leave on their own
        ``expires_at``, stamped at capture from the horizon in force when they were
        written; this only *observes* — it asks the ``MemoryStore`` whether the
        conversation's channel still holds any episode — and drops a conversation
        record when it holds none (ADR-0283 §8:2). Stated as
        one sequence with the deletion sweep, a live episode would be destroyed
        because its *conversation* was old, and a record stamped under a 30-day
        horizon would die under a later 7-day setting it was never written against.

        A conversation is reclaimable when its channel holds **no episode and** its
        ``last_active_at`` is past the horizon — both, not the first alone. With
        only the first, a conversation whose single turn expired would be dropped
        while its owner still held a working id. "Holds" is ``channel_episode_ids``'
        sense, so an expired episode not yet purged, or one not yet valid, delays it.

        **The horizon shortlists; the store decides.** ``recent`` is read once to
        find candidates whose activity is already past the horizon, and
        ``drop_if_eligible`` then re-checks that under the per-conversation
        exclusion. The shortlist is a reading taken *outside* the exclusion, which
        is safe here precisely because it can only ever **skip** work: a
        conversation that looks active is left alone, and the next sweep catches it.
        Nothing is destroyed on the strength of it, so §9.4's hazard — deciding
        eligibility outside the exclusion and then acting — is not reintroduced.

        With ``retention`` unset there is no horizon to compare against, so reclaim
        is **switched off** rather than guessed at: "keep the episodes forever" is
        not a setting under which conversations should quietly disappear, and
        deletion is then the only thing that removes one.

        Returns:
            How many conversation records were dropped.
        """
        if self._retention is None:
            return 0
        horizon = self._now() - self._retention
        dropped = 0
        for conversation_id in await self._idle_candidates(horizon):
            try:
                if await self._is_emptied(conversation_id) and (
                    await self._conversations.drop_if_eligible(conversation_id)
                ):
                    dropped += 1
            except UnknownConversationError:
                # Reclaimed or deleted between the shortlist and here.
                continue
        return dropped

    async def _idle_candidates(self, horizon: datetime) -> list[str]:
        """The ids of unstamped conversations whose activity predates ``horizon``.

        Collected in full *before* anything is dropped, so this walk's own drops
        cannot shift the offsets underneath it. Offset paging over a store other
        writers are using may still skip or repeat a row, which ADR-0073 §2 names
        and accepts — and the reclaim is idempotent by re-running, so a skipped
        conversation is picked up next time rather than lost.
        """
        candidates: list[str] = []
        offset = 0
        while True:
            page = await self._conversations.recent(limit=_RECLAIM_PAGE, offset=offset)
            candidates.extend(one.id for one in page if one.last_active_at <= horizon)
            if len(page) < _RECLAIM_PAGE:
                return candidates
            offset += len(page)

    async def _is_emptied(self, conversation_id: str) -> bool:
        """Whether the conversation's channel holds **no** episode (ADR-0283 §8:2).

        The half of the reclaim precondition ``ConversationStore`` cannot answer
        (golden rule 1). One read: ``channel_episode_ids`` returns identifiers alone
        and filters by nothing, so a single held episode — live, expired but not yet
        purged, or not yet valid — settles the question, and reclaim destroys nothing
        it finds.
        """
        held = await self._memory.channel_episode_ids(
            conversation_channel(conversation_id), limit=1
        )
        return not held

    # --- listing (§2) --------------------------------------------------------

    async def recent(self, *, limit: int = _RECLAIM_PAGE, offset: int = 0) -> list[Conversation]:
        """List conversations by last activity, most recent first (§2).

        The read that lets the hub answer "which conversation?", because a
        stateless client cannot: without it, "continue yesterday's conversation"
        would require the *client* to have kept the id. Relayed to the store
        unchanged — the order and the page are its contract, and a stamped
        conversation is absent from it by construction.
        """
        return await self._conversations.recent(limit=limit, offset=offset)

    def _now(self) -> datetime:
        """The guarded clock's reading, as this stage's own error.

        Raises:
            ConversationStoreError: If the reading is naive, indeterminate, or
                outside the localizable range. This stage's failures reach a caller
                as store failures, and ``core`` defines no error for
                `orchestration` (ADR-0026 §4).
        """
        try:
            return self._clock()
        except ClockReadingError as exc:
            raise ConversationStoreError(str(exc)) from exc


__all__ = [
    "BELIEF_KINDS",
    "CAPTURE_CONFIDENCE",
    "HISTORY_REPLAY_BOUND",
    "AssembledHistory",
    "ConversationDigest",
    "ConversationLifecycle",
    "ParkingOrigin",
    "activation_ending",
    "check_devices_fit",
    "check_message_fits",
    "conversation_channel",
    "conversation_state",
    "episodes_on_place",
    "fit_changes",
    "fit_transcript",
]

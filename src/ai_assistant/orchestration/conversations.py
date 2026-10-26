"""The conversation lifecycle stage: every sequence that spans both durable stores.

ADR-0074 §9's coordinator ruling in one object, as ADR-0283 partially supersedes
it. A conversation's history, membership and deletion are the episodes on its
channel (``ChannelIdentity("conversation", <id>)``), which the ``MemoryStore``
holds; the ``ConversationStore`` holds the conversation and its chat space. A
``ConversationStore`` asked
whether a conversation still has live episodes would have to reach into memory and
break golden rule 1, so this stage — the one place that legitimately holds both
handles by injection — owns the cross-store sequences:

* **history** (ADR-0283 §4; ADR-0284 §6:2) — every live episode of the
  conversation in number order within the replay bound;
* **deletion** (§8, as ADR-0293 §2:3 partially supersedes it) — stamp, which
  deletes the transcript, then drop the record conditionally, and **destroy no
  episode**: deleting a conversation forgets nothing;
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

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ConversationStoreError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    ActivationEnding,
    ChannelIdentity,
    ChatChanges,
    ChatStreamChunk,
    ConversationDigest,
    ConversationStartedChange,
    ConversationState,
    DeviceChange,
    DeviceChanges,
    DevicesChangedChange,
    EpisodicMemory,
    MessageAddedChange,
    NewMessage,
    ProcessingReason,
    ProcessingStatus,
    TranscriptMessage,
    TranscriptPage,
)
from ai_assistant.orchestration.activation_writer import ActivationWriter
from ai_assistant.orchestration.payloads import canonical_payload, check_payload

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        StoryStore,
    )
    from ai_assistant.core.types import (
        ChatDevice,
        Conversation,
        DeviceConversation,
        MemoryRecord,
        MessageReceipt,
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

#: How many conversations the retention reclaim shortlists per ``recent`` page.
_RECLAIM_PAGE = 50

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
#: status (ADR-0293 §8:3). An activation that answered or heard no words is done; one
#: that failed could not finish; one cut short — a restart's close among them (ADR-0286
#: §7) — was interrupted. No status waits since ADR-0318 §5:1 retired ``waiting``.
_ENDINGS: Final[dict[ProcessingStatus, ActivationEnding]] = {
    ProcessingStatus.COMPLETED: ActivationEnding.DONE,
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
    if record.reason is ProcessingReason.STOPPED:
        # ADR-0295 §3:4: a stop is told apart from every other interruption.
        return ActivationEnding.STOPPED
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


def episode_conversation(record: MemoryRecord | None) -> str | None:
    """The conversation ``record`` is an episode of an activation started from, or ``None``.

    Read as :func:`started_from` reads a channel: the trigger's ``channel`` once the
    pass has named it, else its ``target``. A record that is no episode, or an episode
    of another channel, names none. What a forget reads before it destroys a record,
    so the conversation whose current state the episode was read into is known
    (ADR-0296 §4:9).
    """
    if not isinstance(record, EpisodicMemory) or record.processing_record is None:
        return None
    trigger = record.processing_record.trigger
    for channel in (trigger.channel, getattr(trigger, "target", None)):
        if isinstance(channel, ChannelIdentity) and channel.channel_type == "conversation":
            return channel.instance_id
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
    and every id known is named, each one the stop control stops (ADR-0349 §4:3-§4:4,
    §8:1: several may run from one conversation at once). It is held in
    process, so an activation whose episode was forgotten or whose capture failed
    still shows, and **an open episode is never read as running**: one a failed
    capture's compensation could not delete stays open until a restart closes it
    (ADR-0286 §5), long after its activation ended.

    **How the last one ended is read from the episodes on the place**, the
    assistant's durable record of its activations, so a restart that closed an
    activation as interrupted is read back as interrupted (§9:2). Shared by the
    engine and the canonical fake engine, so both read one state the same way:

    * the place's newest **ended** episode is the last activation that ended, and its
      status says how (:func:`activation_ending`);
    * **except where its matter was taken over** (ADR-0352 §5:1-§5:3): an activation
      absorbed or whose input was taken is never the one whose ending is shown. Its
      episode names the activation that took its matter, which is followed forward to
      the one that took it last; where that one was started from this conversation and
      has ended, its ending is shown, and otherwise, while it runs, where it was started
      from another place, or where its episode is not found, the taken-over episode is
      passed over and the next newest ended one is read the same way, so the state keeps
      the ending it showed before the hand-over (:func:`_shown_ending`).

    An activation that wrote no episode — capture degraded, or forgotten — is not
    seen, and a conversation whose episodes were forgotten reads as idle: what the
    assistant forgot it no longer knows ran.

    Raises:
        MemoryStoreError: If the episodes cannot be read.
    """
    channel = conversation_channel(conversation_id)
    held = tuple(running)
    known = [one for one in held if one is not None]
    # ADR-0349 §4:4, §10:3: every running activation started from it whose id is known,
    # since every message starts its own (§8:1).
    return ConversationState(
        working=bool(held),
        activation_ids=tuple(dict.fromkeys(known)),
        last_ended=await _shown_ending(memory, channel),
    )


#: How much wider each read of a conversation's newest ended episodes is than the last,
#: while every one read was taken over, up to the read's own bound; past it, the older
#: episodes are enumerated and read in pages of the same bound.
_ENDING_WIDER: Final = 4
_ENDING_BOUND: Final = 1000


async def _shown_ending(memory: MemoryStore, channel: ChannelIdentity) -> ActivationEnding | None:
    """How the activation a conversation shows the ending of ended (ADR-0352 §5:1-§5:3).

    Its newest ended episode, read newest first, passing over each whose activation's
    matter was taken over and whose taker, followed forward, is not this conversation's
    own and ended. Where the taker is, it is the taker's ending. ``None`` where nothing
    the conversation started has ended that is not passed over.

    The newest are read in widening pages, so the common case reads one episode. Where
    every one of the newest the read's bound reaches was passed over, the older ones are
    enumerated and read newest first, so no ending the conversation showed before is
    lost however many hand-overs came after it.

    Raises:
        MemoryStoreError: If the episodes cannot be read.
    """
    limit = 1
    while True:
        page = await memory.channel_episodes(channel, limit=limit)
        for entry in reversed(page.entries):
            shown, ending = await _judged(memory, entry.record, channel)
            if shown:
                return ending
        if len(page.entries) < limit:
            return None
        if limit >= _ENDING_BOUND:
            return await _older_ending(memory, channel, below=page.entries[0].number)
        limit = min(limit * _ENDING_WIDER, _ENDING_BOUND)


async def _older_ending(
    memory: MemoryStore, channel: ChannelIdentity, *, below: int
) -> ActivationEnding | None:
    """:func:`_shown_ending` over the episodes numbered below ``below``, newest first.

    Enumerated with ``channel_episode_ids``, which reads every record held on the
    channel, and read with ``get_many``, which keeps only what is live, as
    ``channel_episodes`` does; an open episode is passed over, as that read never
    reads one.

    Raises:
        MemoryStoreError: If the episodes cannot be read.
    """
    older: list[str] = []
    after: int | None = None
    while held := await memory.channel_episode_ids(channel, after=after, limit=_ENDING_BOUND):
        older.extend(one.episode_id for one in held if one.number < below)
        if held[-1].number >= below:
            break
        after = held[-1].number
    for end in range(len(older), 0, -_ENDING_BOUND):
        named = older[max(0, end - _ENDING_BOUND) : end]
        read = await memory.get_many(named)
        for episode_id in reversed(named):
            record = read.get(episode_id)
            if (
                not isinstance(record, EpisodicMemory)
                or record.processing_record is None
                or record.processing_record.is_open
            ):
                continue
            shown, ending = await _judged(memory, record, channel)
            if shown:
                return ending
    return None


async def _judged(
    memory: MemoryStore, record: EpisodicMemory, channel: ChannelIdentity
) -> tuple[bool, ActivationEnding | None]:
    """Whether the state shows an ending for ``record``, an ended episode, and which.

    Its own, where its matter was not taken over; the taker's, followed forward, where
    that one was started from ``channel`` and has ended; and none, passing it over,
    otherwise (ADR-0352 §5:3).

    Raises:
        MemoryStoreError: If an episode cannot be read.
    """
    processing = record.processing_record
    if processing is None or processing.taken_over_by is None:
        return True, activation_ending(record)
    taker = await _last_taker(memory, processing.taken_over_by)
    if taker is not None and started_from(taker, channel) is not None:
        return True, activation_ending(taker)
    return False, None


async def _last_taker(memory: MemoryStore, taker: str) -> EpisodicMemory | None:
    """The frozen episode of the activation that took a matter last (ADR-0352 §5:3).

    Followed forward from ``taker`` through each episode that records an activation that
    took its matter in turn. ``None`` where one along the way still runs, so its episode
    is open, or its episode is not found.

    Raises:
        MemoryStoreError: If an episode cannot be read.
    """
    seen: set[str] = set()
    at = taker
    while at not in seen:
        seen.add(at)
        record = await memory.get(f"activation:{at}")
        if not isinstance(record, EpisodicMemory) or record.processing_record is None:
            return None
        processing = record.processing_record
        if processing.is_open:
            return None
        if processing.taken_over_by is None:
            return record
        at = processing.taken_over_by
    # A chain only ever moves on to an activation running when it took the matter, so it
    # never comes back on itself; were it to, nothing along it is shown.
    return None


#: The widest instant and number a recorded message can carry, so the probe below
#: measures the most its record can cost rather than what it costs today.
_WIDEST_AT: Final = datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)
_WIDEST_NUMBER: Final = 2**63 - 1


def _widest_records(
    conversation_id: str, message: NewMessage
) -> tuple[TranscriptPage, ChatChanges, ChatStreamChunk]:
    """The three records ``message``'s own record could cost to read back.

    The one-entry transcript page, the one-change page, and the change stream's chunk
    carrying the change (ADR-0298 §7:3), measured at the widest position, sequence
    number and instant it could be recorded with, and a reply reference as wide as the
    one it names.
    """
    recorded = TranscriptMessage(
        conversation_id=conversation_id,
        position=_WIDEST_NUMBER,
        written_at=_WIDEST_AT,
        author=message.author,
        text=message.text,
        # As wide as the reply the message names, and below the probe's own position,
        # which a recorded message's reference always is.
        replies_to=None
        if message.replies_to is None
        else min(message.replies_to, _WIDEST_NUMBER - 1),
        options=message.options,
        cut_off=message.cut_off,
        device_id=message.device_id,
        message_id=message.message_id,
    )
    added = MessageAddedChange(seq=_WIDEST_NUMBER, message=recorded)
    return (
        TranscriptPage(conversation_id=conversation_id, entries=(recorded,), as_of=_WIDEST_NUMBER),
        ChatChanges(changes=(added,), next_after=_WIDEST_NUMBER),
        ChatStreamChunk(change=DeviceChange(change=added)),
    )


def check_message_fits(conversation_id: str, message: UserMessage, *, max_bytes: int) -> None:
    """Refuse a message whose own record could not be read back within the limit.

    A message is accepted only where a page holding it alone — the transcript's and
    the change stream's — and the change stream's chunk carrying it (ADR-0298 §7:3)
    fit the payload limit, measured at the widest position, sequence number and
    instant it could be recorded with. Otherwise a message the conversation recorded
    would be one no read could return, and a device's cursor would stop at it for
    good: :func:`fit_transcript` and :func:`fit_changes` can shorten a page to one
    entry and no further, and a chunk carries one change. Shared by the engine and the
    canonical fake engine.

    Raises:
        OversizedValueError: If any of the three would exceed ``max_bytes``.
    """
    page, changes, chunk = _widest_records(conversation_id, message.as_new_message())
    check_payload(
        page,
        max_bytes=max_bytes,
        subject="the transcript page holding the message write_message() was given",
    )
    check_payload(
        changes,
        max_bytes=max_bytes,
        subject="the change recording the message write_message() was given",
    )
    check_payload(
        chunk,
        max_bytes=max_bytes,
        subject="the change stream's chunk carrying the message write_message() was given",
    )


def _prefix_fits(conversation_id: str, message: NewMessage, length: int, *, max_bytes: int) -> bool:
    """Whether the record of ``message`` cut to ``length`` characters fits ``max_bytes``.

    Measured on the record as the probe builds it, but **unvalidated**, so a prefix
    that is blank — which no message may be — is still measured: the size grows with
    the length whatever the characters, and the search over it has to see every
    length to stay a search (a blank prefix is refused afterwards, not here).
    """
    page, _, _ = _widest_records(conversation_id, message)
    (entry,) = page.entries
    assert isinstance(entry, TranscriptMessage)  # noqa: S101 — the probe holds one message
    cut = TranscriptMessage.model_construct(
        **{**dict(entry), "text": message.text[:length], "cut_off": True}
    )
    added = MessageAddedChange.model_construct(seq=_WIDEST_NUMBER, message=cut)
    return all(
        len(canonical_payload(one)) <= max_bytes
        for one in (
            page.model_copy(update={"entries": (cut,)}),
            ChatChanges.model_construct(changes=(added,), next_after=_WIDEST_NUMBER),
            ChatStreamChunk.model_construct(
                change=DeviceChange.model_construct(change=added, snapshot=None),
                state=None,
                roles=None,
                heartbeat=False,
            ),
        )
    )


def fitted_message(conversation_id: str, message: NewMessage, *, max_bytes: int) -> NewMessage:
    """``message`` cut short until its own record can be read back within the limit.

    The writer's size bound, enforced at the actuator (ADR-0293 §7:3): the assistant's
    message is held to the transcript's bound by its type, and to what one read can
    return by this, for :func:`check_message_fits`' reason — a recorded message no read
    could return would stop every device's cursor at it. A message that is cut is
    marked cut off, so it is never read as a complete answer (§5:2, §6:16). The
    longest prefix that fits is found by bisection over its length — the record's size
    only grows with it — each probe one encoding of at most the message itself.

    Raises:
        OversizedValueError: If the longest prefix that fits is blank, which no message
            may be — only a limit too small for a message's own frame brings it about.
    """
    records = _widest_records(conversation_id, message)
    if all(len(canonical_payload(one)) <= max_bytes for one in records):
        return message
    # `low` always fits (the empty prefix is the frame alone); `high` never does.
    low, high = 0, len(message.text)
    while high - low > 1:
        middle = (low + high) // 2
        if _prefix_fits(conversation_id, message, middle, max_bytes=max_bytes):
            low = middle
        else:
            high = middle
    if not message.text[:low].strip():
        for one in records:
            check_payload(one, max_bytes=max_bytes, subject="the assistant's message")
        raise AssertionError("an oversized message was unexpectedly admitted")
    # Every property kept but the text and the cut, the claim it is written under among
    # them (ADR-0350 §12:9): a message cut to fit is still the one its effect record names.
    return NewMessage.model_validate(
        {**message.model_dump(), "text": message.text[:low], "cut_off": True}
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
    (§3:3) and in the change stream's chunk (ADR-0298 §7:3). A set whose one-change
    page, chunk or digest would exceed the payload limit would stop every cursor at
    that change, since :func:`fit_changes` can shorten a page to one change and no
    further and a chunk carries one change; so it is refused before it is recorded,
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
        # The change stream's chunk carrying it, with the snapshot a device it adds is
        # given shortened to none, which is as far as §7:8 shortens it.
        snapshot = None if change.conversation_id is None else ()
        check_payload(
            ChatStreamChunk(change=DeviceChange(change=change, snapshot=snapshot)),
            max_bytes=max_bytes,
            subject="the change stream's chunk carrying the devices given",
        )
    check_payload(
        ConversationDigest(
            id=named,
            started_at=_WIDEST_AT,
            last_turn_at=_WIDEST_AT,
            recorded_turns=_WIDEST_NUMBER,
            state=ConversationState(
                working=True,
                activation_ids=(_PROBE_CONVERSATION,),
                last_ended=ActivationEnding.COULDNT_FINISH,
            ),
            devices=held,
        ),
        max_bytes=max_bytes,
        subject="the conversation read carrying the devices given",
    )


def _fitting_count(sizes: Sequence[int], *, base: int, max_bytes: int) -> int:
    """How many of ``sizes``, taken from the front, fit beside ``base`` bytes.

    A page's encoding is its frame with no entry, plus each entry's own encoding,
    plus a comma between two: canonical JSON is additive over an array's members, so
    each entry is encoded once and the page is never re-encoded per candidate.
    """
    total = base
    for count, size in enumerate(sizes):
        total += size + (1 if count else 0)
        if total > max_bytes:
            return count
    return len(sizes)


def fit_transcript(page: TranscriptPage | None, *, max_bytes: int) -> TranscriptPage | None:
    """The page shortened from its oldest end until it fits the payload limit.

    A snapshot keeps its most recent entries, and the first position left is where
    the next ``before`` reads from, so nothing is lost (ADR-0293 §5:13). Where not
    even one entry fits, the original page earns the ordinary size error. Each entry
    is encoded once (:func:`_fitting_count`), and the page chosen is measured once
    more, so the work is linear in the page.

    Raises:
        OversizedValueError: If no non-empty page fits.
    """
    if page is None or len(canonical_payload(page)) <= max_bytes:
        return page
    newest_first = [len(canonical_payload(one)) for one in reversed(page.entries)]
    base = len(canonical_payload(page.model_copy(update={"entries": ()})))
    count = _fitting_count(newest_first, base=base, max_bytes=max_bytes)
    if count:
        fitted = page.model_copy(update={"entries": page.entries[len(page.entries) - count :]})
        check_payload(fitted, max_bytes=max_bytes, subject="the result of transcript()")
        return fitted
    check_payload(page, max_bytes=max_bytes, subject="the result of transcript()")
    raise AssertionError("an oversized transcript page was unexpectedly admitted")


def fit_changes(page: ChatChanges, *, max_bytes: int) -> ChatChanges:
    """The changes shortened from their newest end until they fit the payload limit.

    ``next_after`` becomes the last change returned, so the next read resumes after
    it and nothing is lost (ADR-0293 §5:11). Where not even one change fits, the
    original page earns the ordinary size error. The frame is measured at the page's
    own ``next_after``, which no kept change's sequence number exceeds, so the count
    chosen is never too large; each change is encoded once.

    Raises:
        OversizedValueError: If no non-empty page fits.
    """
    if len(canonical_payload(page)) <= max_bytes:
        return page
    sizes = [len(canonical_payload(one)) for one in page.changes]
    base = len(canonical_payload(ChatChanges(next_after=page.next_after)))
    count = _fitting_count(sizes, base=base, max_bytes=max_bytes)
    if count:
        kept = page.changes[:count]
        fitted = ChatChanges(changes=kept, next_after=kept[-1].seq)
        check_payload(fitted, max_bytes=max_bytes, subject="the result of chat_changes()")
        return fitted
    check_payload(page, max_bytes=max_bytes, subject="the result of chat_changes()")
    raise AssertionError("an oversized changes page was unexpectedly admitted")


def fit_stream_chunk(chunk: ChatStreamChunk, *, max_bytes: int) -> ChatStreamChunk:
    """A change stream chunk with its snapshot shortened until it fits (ADR-0298 §7:8).

    The snapshot keeps the newest of its messages that fit with the change within the
    payload limit, shortened from its oldest end and to none if need be, so the chunk
    always fits and a cursor never stops on a snapshot too large to send; the device
    loads older messages by reading the transcript. A chunk with no snapshot is
    measured as it is.

    Raises:
        OversizedValueError: If the chunk does not fit even with an empty snapshot,
            which a change the store recorded within the limit cannot reach.
    """
    subject = "a chunk of follow_chat()"
    if len(canonical_payload(chunk)) <= max_bytes:
        return chunk
    entry = chunk.change
    if entry is None or entry.snapshot is None:
        check_payload(chunk, max_bytes=max_bytes, subject=subject)
        return chunk
    snapshot = entry.snapshot
    base = len(
        canonical_payload(ChatStreamChunk(change=DeviceChange(change=entry.change, snapshot=())))
    )
    newest_first = [len(canonical_payload(one)) for one in reversed(snapshot)]
    count = _fitting_count(newest_first, base=base, max_bytes=max_bytes)
    kept = snapshot[len(snapshot) - count :] if count else ()
    fitted = ChatStreamChunk(change=DeviceChange(change=entry.change, snapshot=kept))
    check_payload(fitted, max_bytes=max_bytes, subject=subject)
    return fitted


class ConversationLifecycle:
    """Owns every ``ConversationStore``/``MemoryStore`` sequence (ADR-0074 §9)."""

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        memory: MemoryStore,
        retention: timedelta | None,
        now: Clock = _utcnow,
        stories: StoryStore | None = None,
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

        It is a **required** keyword with no default, deliberately. ADR-0074 §7 warns
        that an implementation inheriting a ``None`` default would ship unbounded
        episodic retention while looking like it followed the ADR; a seam with no
        default cannot inherit one at all, and the one place the default is decided is
        ``core.config.Settings``.

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
            stories: The story store whose position each episode's admission write
                records (ADR-0347 §4:1), handed to the writer and read by nothing
                else here. With none, no episode records a position.
        """
        self._conversations = conversations
        self._memory = memory
        self._retention = retention
        self._clock = checked_clock(now, owner="ConversationLifecycle")
        self.activation_writer = ActivationWriter(
            conversations=conversations,
            memory=memory,
            retention=retention,
            now=now,
            stories=stories,
        )

    @property
    def chat_space(self) -> ConversationStore:
        """The hosted medium the chat's reader reads and its writer writes (ADR-0293 §6).

        The same store every act in the medium relays to, so the reader's bookkeeping,
        the transcript it brings in and the messages the writer adds are the ones the
        devices read.
        """
        return self._conversations

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

    async def conversation_devices(self, conversation_id: str) -> tuple[ChatDevice, ...] | None:
        """Read one conversation's devices, or ``None`` where it is not held (§3:3)."""
        return await self._conversations.conversation_devices(conversation_id)

    # --- one device's view (ADR-0296 §4, ADR-0298 §5) ------------------------

    async def device_conversations(
        self, device_id: str, *, limit: int, offset: int = 0
    ) -> list[DeviceConversation]:
        """List the conversations ``device_id`` reads, as ``recent`` orders them."""
        return await self._conversations.device_conversations(device_id, limit=limit, offset=offset)

    async def device_changes(self, device_id: str, *, after: int, limit: int) -> DeviceChanges:
        """Read the changes after a cursor that ``device_id`` may see (ADR-0296 §4:5).

        Each change that adds the device as a reader carries the conversation's
        snapshot as of that change (ADR-0298 §7:6).
        """
        return await self._conversations.device_changes(device_id, after=after, limit=limit)

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
        self.activation_writer.forgetting_conversation(conversation_id)
        forgot = False
        for episode_id in await episodes_on_place(self._memory, conversation_id):
            self.activation_writer.forgetting(episode_id)
            forgot = await self._memory.delete(episode_id) or forgot
        return forgot

    async def delete(self, conversation_id: str) -> bool:
        """Delete a conversation: stamp it, then drop the record (§8).

        ADR-0283 §8:1 as ADR-0293 §2:3 partially supersedes it: deleting removes the
        conversation and its transcript, **and none of the episodes on its place**.
        The stamp is the act in the medium — the store deletes the transcript, the
        devices and the reader's bookkeeping in the same step and records the change
        — and the record is dropped once its grace has passed. If this process dies
        between the steps the stamped record is still there, so
        :meth:`sweep_deletions` finishes it (ADR-0076).

        Returns:
            ``True`` if this call stamped the conversation; ``False`` if it was
            already stamped or the id names nothing. Either way the sweep behind it
            is run, because the deletion is re-runnable.

        Raises:
            ConversationStoreError: If the store cannot be read or written.
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
        """Drop the stamped record once its grace has passed (§8).

        ADR-0283 §8:1's last step, as ADR-0293 §2:3 leaves it. **No episode is
        destroyed**: deleting a conversation forgets nothing, and its episodes stay on
        its place until the user forgets them (ADR-0293 §2:4). Idempotent: a run that
        dies part-way is re-run from the beginning.

        Returns:
            Whether the record was dropped. ``False`` while the grace still holds —
            the tombstone is deliberately kept alive past the deletion so a capture
            that commits and then dies is still swept.
        """
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
    "CAPTURE_CONFIDENCE",
    "ConversationDigest",
    "ConversationLifecycle",
    "activation_ending",
    "check_devices_fit",
    "check_message_fits",
    "conversation_channel",
    "conversation_state",
    "episodes_on_place",
    "fit_changes",
    "fit_transcript",
    "fitted_message",
]

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
* **deletion** (§8) — stamp, destroy every episode the conversation's channel
  holds, drop the record conditionally;
* **retention reclaim** (§8) — which **destroys nothing**: it only asks whether the
  channel still holds an episode, and drops a conversation record that holds none.

Capture itself is the :class:`~ai_assistant.orchestration.activation_writer.ActivationWriter`'s
(ADR-0283 §7), which this stage builds over the same three stores.

**The two sweeps are opposite, and collapsing them is the error to avoid.**
Finishing a user deletion destroys episodes because that is the request being
carried out. Retention reclaim destroys nothing, because episodes leave on their
own ``expires_at``, stamped at capture from the horizon in force when they were
written. Stated as one sequence, a retention sweep would destroy a live episode
for the crime of belonging to an old conversation.

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
    ChannelIdentity,
    ConversationDigest,
    MemoryKind,
)
from ai_assistant.orchestration.activation_writer import ActivationWriter

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        ParkedReads,
        TranscriptArchiveWriter,
    )
    from ai_assistant.core.types import (
        Conversation,
        MemoryRecord,
        ParkedBinding,
        SpokenDelivery,
        SpokenDeliveryReport,
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

#: How many identifiers one ``channel_episode_ids`` page asks for while a deletion
#: or a reclaim walks a conversation's channel (ADR-0283 §8). The read's own bound.
_CHANNEL_PAGE: Final = 1000


def conversation_channel(conversation_id: str) -> ChannelIdentity:
    """The channel a conversation's episodes are written on (ADR-0275 §4:5, ADR-0283 §4)."""
    return ChannelIdentity(channel_type="conversation", instance_id=conversation_id)


def _utcnow() -> datetime:
    return datetime.now(UTC)


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

    def __init__(  # noqa: PLR0913 — the three stores this stage spans, the switch that gates the third's write, the horizon both the episodes and the index are judged against, and the clock; every one is an injected collaborator or its own configuration
        self,
        *,
        conversations: ConversationStore,
        memory: MemoryStore,
        archive: TranscriptArchiveWriter,
        archive_enabled: bool,
        retention: timedelta | None,
        now: Clock = _utcnow,
        parked_reads: ParkedReads | None = None,
    ) -> None:
        """Wire the stage from the three injected stores.

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
            archive: The transcript archive, as its **narrow** seam (ADR-0225 §10).
                A :class:`~ai_assistant.core.protocols.TranscriptArchiveWriter` and
                never a ``TranscriptArchive``: §4's turn-path fence gives the one
                component that writes an entry no way to read one back, and this
                annotation is the whole of the narrowing —
                ``self._archive.search(...)`` fails ``mypy`` whatever object the
                composition root passed. **Required with no default**, in §10's own
                words: "a composition that omits it does not type-check".
            archive_enabled: Whether a captured turn is also archived (ADR-0225 §6's
                ``transcript_archive_enabled``). It gates the **write alone**:
                turning it off destroys nothing, and both destroys below still run,
                so entries already held stay searchable and stay destroyable and a
                configuration change is never a silent deletion. Required with no
                default for ``retention``'s reason — the one place the default is
                decided is ``core.config.Settings``.
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
                ``archive`` and ``retention`` above and takes
                :class:`~ai_assistant.orchestration.recipient_grants.RecipientGrantOperations`'
                choice for the same object one seam over. A stage with no archive cannot
                carry out §8 at all; a stage with no park store carries it out exactly as
                it did before this decision, because a deployment that wired none holds no
                park for any conversation. ``None`` drops nothing because there is nothing
                to drop.
        """
        self._conversations = conversations
        self._memory = memory
        self._archive = archive
        self._archive_enabled = archive_enabled
        self._retention = retention
        self._clock = checked_clock(now, owner="ConversationLifecycle")
        self._parked_reads = parked_reads
        self.activation_writer = ActivationWriter(
            conversations=conversations,
            memory=memory,
            archive=archive,
            archive_enabled=archive_enabled,
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

    async def digest(self, conversation_id: str) -> ConversationDigest | None:
        """The count and span a deletion ceremony shows, or ``None`` (ADR-0283 §4:2).

        Two reads and no walk: the record for the span and ``last_turn_at``, which is
        the conversation's own, and an **unfiltered** ``channel_episodes`` read of its
        channel, whose ``total`` is the count — every live episode on the channel,
        eligible or not, whatever the page held.

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
        return ConversationDigest(
            id=conversation.id,
            started_at=conversation.started_at,
            last_turn_at=conversation.last_turn_at,
            recorded_turns=page.total,
        )

    async def delete(self, conversation_id: str) -> bool:
        """Destroy a conversation: stamp, purge, drop (§8, ADR-0004 §6).

        The three steps normally run to completion here, and the tombstone is what
        makes a crash survivable rather than final. If this process dies at any
        point — or a racing capture writes its episode after step 2 — the stamped
        record is still there and the episodes are still on the conversation's
        channel, so :meth:`sweep_deletions` finishes it (ADR-0283 §8).

        **Step 2 destroys this conversation's parked reads too** (ADR-0244 §3), through
        ``ParkedReads.drop_for_conversation`` and never through a concrete store —
        :meth:`_finish_deletion` carries the placement and its argument.

        Returns:
            ``True`` if this call stamped the conversation; ``False`` if it was
            already stamped or the id names nothing. Either way the sweep behind it
            is run, because §8's protocol is explicitly re-runnable.

        Raises:
            ConversationStoreError: If the store cannot be read or written.
            MemoryStoreError: If an episode could not be destroyed. The tombstone
                stands and the next sweep finishes the job; reporting success over
                content the user asked to be gone would be the worse failure.
            TranscriptArchiveError: If the transcript could not be destroyed, which
                aborts step 2 before any episode is deleted (ADR-0225 §5). The
                tombstone stands here too, for the same reason.
            AssistantError: If this conversation's parked reads could not be dropped,
                which aborts step 2 in the same place and for the same reason.
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
        process that died between the stamp and the drop left episodes that were
        never destroyed and an index that outlived its grace indefinitely.

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
        """Destroy this conversation's transcript and episodes, then ask for the drop (§8).

        ADR-0283 §8:1, in order: the archive's ``discard_conversation``, the parked
        reads' drop, then **every episode ``channel_episode_ids`` returns for the
        conversation's channel**, page by page until a read is empty, then
        ``drop_if_eligible``. That enumeration is what the store physically holds —
        expired but unpurged, not yet valid and ineligible episodes included — and no
        read filtered by liveness, validity or eligibility is used in its place
        (ADR-0275 §6:6). Idempotent by re-walking: a run that dies part-way is re-run
        from the beginning, and the episodes it already deleted are no longer on the
        channel.

        **The archive discard is the first action of §8's step 2** (ADR-0225 §5),
        before any episode is deleted, on the rule §5 draws from ADR-0074 §8's own
        third mitigation: the residue of a partial failure must be the one the user
        can still reach and destroy. A crash after it leaves *records* present, which
        ``forget`` and this very sweep destroy on the next attempt; the other order
        would leave retained text after a deletion the user was told succeeded.

        **A discard that raises aborts the call here, and no clause of §8 changes.**
        Every episode on the channel is still there, so step 3's own condition is
        unmet by §8's own terms — the tombstone survives and the reclaim re-runs the
        whole of step 2, this discard included, in the deleting call, at engine start
        and later on the hub's schedule. No third conjunct is added to step 3.

        **A second run finding the archive already empty is the conforming answer.**
        ``discard_conversation`` destroys what it matches or nothing and returns zero
        for a conversation with no entries (ADR-0225 §5), so the run that follows a
        ``MemoryStore.delete`` failure part-way through step 2 carries the remaining
        episode deletions through to the drop rather than treating the zero as an
        error.

        **The parked reads go second, and the position is argued rather than free**
        (ADR-0244 §3). It is inside **step 2** and never after step 3, because
        ``drop_if_eligible`` removes the record and its tombstone — after which nothing
        enumerates this conversation again, and a park dropped there and interrupted
        would be strandable with only its own deadline to free it. That is ADR-0238 §8's
        stranding failure, the one ADR-0244 §3 contrasts a park against, and it is closed
        here by running before the drop rather than by a reconciliation walk, a tombstone
        of its own or a second lifecycle — none of which §3 admits.

        It goes **after** the archive discard, which ADR-0225 §5 fixes as "the first
        action of §8's step 2", and **before** the episode walk, so a call arriving for
        a conversation another sweep already dropped still reaches the parks — the one
        route to them ADR-0244 §3 names besides the deadline.

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
            TranscriptArchiveError: If the transcript could not be destroyed. Nothing
                below runs, and the tombstone stands.
            AssistantError: If the parked-read store could not be written. Nothing below
                runs and the tombstone stands, for the archive discard's own reason: the
                residue of a partial failure has to be one the user can still reach and
                destroy, and a park is reachable through the enumeration and self-clearing
                on its deadline.
        """
        await self._archive.discard_conversation(conversation_id)
        if self._parked_reads is not None:
            await self._parked_reads.drop_for_conversation(conversation_id)
        channel = conversation_channel(conversation_id)
        after: int | None = None
        while True:
            held = await self._memory.channel_episode_ids(channel, after=after, limit=_CHANNEL_PAGE)
            if not held:
                break
            for one in held:
                await self._memory.delete(one.episode_id)
            after = held[-1].number
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
    "conversation_channel",
]

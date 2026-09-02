"""The capture/lifecycle stage: every sequence that spans both durable stores.

ADR-0074 §9's coordinator ruling in one object. Whether a conversation still has
live turns is a ``MemoryStore`` fact — expiry and deletion are enforced there —
while the conversation index holds only ids, so a ``ConversationStore`` asked to
answer it would have to reach into memory and break golden rule 1. This stage is
the one place that legitimately holds both handles by injection, and it therefore
owns **all four** cross-store sequences:

* **capture** (§3) — append the turn (the intent log), write its episode, then
  verify the conversation still stands;
* **deletion** (§8) — stamp, destroy the episodes the index names, drop the
  record conditionally;
* **retention reclaim** (§7) — which **destroys nothing**: it only asks whether
  any turn still resolves, and drops a conversation record that has none;
* **the user-facing export** (§9) — the conversation half filtered against the
  memory half of *the same* artifact.

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
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    ConversationStoreError,
    MemoryStoreError,
    TranscriptArchiveError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    Capture,
    ConversationDigest,
    EpisodicMemory,
    ExchangeDisposition,
    MemoryKind,
    MemorySource,
    MemoryWrite,
    MemoryWriteMode,
    Modality,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    TranscriptEntry,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import timedelta

    from ai_assistant.core.clock import Clock
    from ai_assistant.core.protocols import (
        ConversationStore,
        MemoryStore,
        TranscriptArchiveWriter,
    )
    from ai_assistant.core.types import (
        Conversation,
        ConversationExport,
        ConversationTurn,
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


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CaptureReport:
    """What became of one turn's durable record (ADR-0074 §3, §9 item 6).

    Attributes:
        conversation_id: The conversation the turn ran under, or ``None`` when
            none could be resolved — a resumption whose parked binding no longer
            names a turn, which §3 ratifies as "not captured at all, and no
            conversation invented".
        episode_id: The id of the episode recording the turn, or ``None`` where no
            index row stands for it — a refused append, or a capture compensated
            because the conversation was deleted underneath it. It is **not**
            ``None`` merely because the episode write failed (ADR-0205 §1): the
            turn's index row exists either way, and that row is what carries the
            turn's delivery, so a report naming it can still be applied.
        degraded: Whether the exchange went **unrecorded**. The turn's answer is
            still the answer — capture failure degrades a turn, it never fails one
            — but it is reported rather than swallowed, because a user whose turns
            are silently not being recorded will not find out until they try to
            continue.
    """

    conversation_id: str | None
    episode_id: str | None = None
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class AssembledHistory:
    """A conversation's recent turns, resolved to records (ADR-0074 §5, ADR-0205 §5).

    Attributes:
        records: The turns' episodes, oldest first, with every id that no longer
            resolves **skipped**: a turn that was deleted, expired, or whose
            episode write never landed is a gap, never an error, so a conversation
            that lost a turn still resumes and never resurrects the deleted one.
        deliveries: What a device reported playing of each of those turns, keyed by
            the episode qualified (ADR-0205 §5). **Every such turn of the tail and
            not only the previous one**, because a report may name a turn that is no
            longer the previous one — a turn whose episode is in front of the
            composing stage carrying words the device did not play must arrive with
            the fact that it did not. It is read off the rows :meth:`history` walked
            for the records themselves, so the count of them costs no second store
            call and no second retrieval. A turn whose row carries no ``delivery``,
            and one whose episode did not resolve, are both simply absent: a
            delivery fact travels with the episode it qualifies and never without
            it.
        degraded: Whether reading them failed outright, which costs the turn its
            continuity exactly as a failed retrieval costs it its personalisation.
    """

    records: tuple[MemoryRecord, ...] = ()
    deliveries: Mapping[str, SpokenDelivery] = field(default_factory=dict)
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class DataExport:
    """Everything a user's "export my data" hands back (ADR-0004 §6, ADR-0074 §9).

    **Not an atomic snapshot of the two stores**, and it does not claim to be:
    both halves are separate reads and no seam spans them (a cross-store
    transaction is deferred to leg 5). What *is* guaranteed is the property that
    keeps the artifact coherent — the conversation half is filtered against the
    memory half of **this** artifact, never against a live read — so no exported
    turn can point at content the artifact does not carry.

    The residue therefore runs one way only: an episode captured, or a
    conversation deleted, mid-export can leave an episode in ``memories`` with no
    turn indexing it. That reads as an un-indexed episode — content the user
    *has*. The reverse, a turn whose episode is absent, cannot happen.

    Attributes:
        memories: Every retained memory record, ``MemoryStore.export``'s own
            snapshot, unfiltered.
        conversations: The conversation snapshot with every turn whose episode is
            absent from ``memories`` dropped, and with it any conversation that
            had turns and has none left.
    """

    memories: tuple[MemoryRecord, ...]
    conversations: ConversationExport


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
        """
        self._conversations = conversations
        self._memory = memory
        self._archive = archive
        self._archive_enabled = archive_enabled
        self._retention = retention
        self._clock = checked_clock(now, owner="ConversationLifecycle")

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
        """The conversation's recent turns, as records, oldest first (§5).

        Read through the index and fetched by id, and **an id that does not
        resolve is skipped, not an error** — deleted, expired, or an intent whose
        episode write never landed all look the same to a reader, and all three are
        gaps rather than faults. The window is the store's configured replay
        bound, because an unbounded replay of a months-old conversation is a prompt
        nobody sized.

        **The tail is one batch read** (ADR-0086 §6, §8 item 7). §5 declined a
        ``get_many`` as "a contract change bought for one caller at a scale where it
        buys nothing measurable", and named the hub as where to revisit it; ADR-0086
        §6 records that that trigger never fired — the hub owns the databases, so a
        resume's *k* reads never cross a socket — and lands the method on the
        argument the deferral actually turned on, with a second caller and a figure.
        This is the resume half of it, and §6 partially supersedes §5 here.

        **Both behaviours the loop had for ratified reasons survive the batch, and
        neither is free.** The order is the *conversation's* ordinal sequence and not
        the mapping's, so the result is assembled by walking ``turns`` and looking
        each id up. And an id that does not resolve is still simply absent from the
        mapping — §6's omission is the same skip ``get`` answering ``None`` was, on
        the identical liveness predicate, so a deleted, expired or never-landed
        episode is a gap here exactly as before.

        Returns:
            The records and whether reading them failed outright.
        """
        try:
            turns = await self._conversations.turns(conversation_id)
            episodes = await self._memory.get_many([turn.episode_id for turn in turns])
            records: list[MemoryRecord] = []
            deliveries: dict[str, SpokenDelivery] = {}
            for turn in turns:
                episode = episodes.get(turn.episode_id)
                if episode is None:
                    continue
                records.append(episode)
                # ADR-0205 §5: paired with the episode it qualifies, off the row
                # this loop already holds. Collected **inside** the liveness check,
                # so a fact whose episode did not resolve is dropped with it — a
                # delivery travelling without the answer it is about is a value that
                # says how long something ran with nothing beside it.
                if turn.delivery is not None:
                    deliveries[turn.episode_id] = turn.delivery
        except ConversationStoreError, MemoryStoreError:
            # Losing continuity costs the answer its history, not its usefulness —
            # so the turn goes on, saying so, exactly as a failed retrieval does.
            _log.warning("conversation_history_degraded", stage="history", exc_info=True)
            return AssembledHistory(degraded=True)
        return AssembledHistory(records=tuple(records), deliveries=deliveries)

    async def conversation_of_binding(self, binding: ParkedBinding) -> ConversationTurn | None:
        """The turn a parked confirmation belongs to, or ``None`` (§3).

        A resumption cannot be *told* which conversation it is in — the adapter
        relays an opaque token and nothing else, and after a restart that token is
        reconstructed from durable state with no live turn behind it — so the
        association is durable and recovered rather than passed. ``None`` for a
        park predating capture, or one whose conversation the user deleted; both
        mean the resumption is not captured and **no conversation is invented** for
        it, because recording it under a fresh conversation would assert one the
        user never had.
        """
        return await self._conversations.turn_of_binding(binding)

    # --- capture (§3, §4, §8) ------------------------------------------------

    async def capture(  # noqa: PLR0913 — the conversation, the rendering, the reply, what became of the pass, the binding a park recorded, the turn's disclosure evaluation, how its user material reached this system, what its supply rested on, and its delivery; every one is a distinct fact about the turn being recorded
        self,
        conversation_id: str,
        *,
        content: str,
        asked: str | None,
        outcome: str | None = None,
        disposition: ExchangeDisposition | None = None,
        parked: ParkedBinding | None = None,
        supplied_withheld: bool = False,
        modality: Modality = Modality.TEXT,
        derived_from_external: bool = False,
        delivery: SpokenDelivery | None = None,
    ) -> CaptureReport:
        """Record one turn: the index entry first, then its episode (§3).

        **The ordering is the protocol, not a preference.** The index entry lands
        first and names the episode before the episode exists, which makes the
        index an intent log: no episode can exist for a conversation without its id
        having been recorded there, so an enumeration of the index names every
        episode that conversation will ever have — including one whose write has
        not landed. That is what lets §8's deletion be finished after a crash. The
        cost is that a crash between the two writes leaves an index entry with no
        episode, which every reader already renders as a gap.

        **The episode is written directly** — a one-element ``write_atomic`` in
        ``INSERT_IF_ABSENT`` mode — and never through ``MemoryWriter.ingest``.
        ADR-0075 partially supersedes ADR-0005's proposal → policy path for exactly
        this producer: capture records what happened and infers nothing, and the
        shipped policy would actively corrupt it (an episode's "conflicts" are
        other episodes, and a ``REINFORCE`` would store the later turn at the
        earlier turn's id). ``add`` is refused for its own reason: it is a
        documented upsert keyed on the caller's id.

        With a store-derived id the insert-if-absent mode is a **guard rather than
        a routine path** — an id derived from a unique conversation and a
        store-proved ordinal collides only if that invariant has broken or a
        foreign producer took a reserved-namespace id. Both are faults, neither is
        a race, and a retry answers neither, so a conflict fails the capture loudly
        and nothing is retried. Capture is attempted **at most once per outcome**
        (ADR-0075 §2): a second attempt would take a second ``append``, allocating a
        second ordinal and a second id, and so record the same exchange twice.

        **The archive entry lands between the index entry and the episode**
        (ADR-0225 §2). The order is the protocol there too, and for a reason of its
        own: ADR-0074 §3 accepts a failed episode write on the ground that "a missing
        episode is the one outcome that loses nothing but the record", which is true
        while the record's whole life is thirty days and less true once there is a
        store whose job is to still hold the exchange in three years. Ordering the
        archive last would make the long-lived copy the one most exposed to the very
        failure §3 accepts. Ordering it first costs nothing §8 does not already
        handle: the index entry still lands before either write, and a crash between
        the two writes leaves exactly the state §3 already ratifies — with the
        transcript intact.

        **The archive write never fails a turn and never fails a capture** (§2). A
        store failure writing it is logged and reported on this capture's own
        degraded outcome exactly as a failed episode write is, the episode write
        proceeds, and nothing is retried. Nor does a landed archive entry make a lost
        episode undegraded: the archive makes the loss smaller and does not make it
        disappear.

        **No entry is written where the caller supplied no ``disposition``** (§10).
        That caller is recording an exchange this system did not drive, and the
        archive holds what this system's own capture recorded; coercing a member
        would recreate for a parked turn exactly the ambiguity the field is carried
        to prevent. ``archive_enabled`` set false likewise stops the write and
        destroys nothing (§6).

        **The verification after the write is the fence, not the clock.** An append
        that succeeded before a deletion stamped the conversation is no evidence
        that it still exists when the episode write commits — the two are separate
        calls on separate stores, and ``write_atomic`` awaits an embedder before it
        reaches its own lock. So this re-reads the conversation afterwards and
        destroys the episode it just wrote if the conversation is stamped or gone.
        Because the episode's id is determined by its own conversation and ordinal,
        that delete can never destroy a record capture did not write.

        Args:
            conversation_id: The conversation to record the turn in.
            content: The canonical text rendering of the exchange — what was asked
                and how it turned out (ADR-0005 §1).
            asked: **What the user said**, in their own words, unrewritten and
                unrendered — the archive entry's user half (ADR-0225 §1). ``None``
                where the pass received no user words at all, which includes the
                resolution of a parked step: the utterance that parked was archived
                at its own address by the pass that parked, and repeating it here
                would render one sentence as though the user had said it twice.
                **Handed to capture, not computed here** — capture judges nothing
                (§4), and this method could not derive it anyway: ``content`` is a
                rendering built for the observer and for retrieval, from which the
                user's sentence is recoverable, if at all, by parsing a prefix this
                system is free to change (ADR-0225 §1).
            outcome: **What the assistant said** — the composed reply, whole, as the
                episode's own ``outcome`` (ADR-0221 §1). ``None`` where the pass
                produced no reply, which is the five paths §1 enumerates; the caller
                passes what its composing stage produced, and this method stores it
                without inspecting it, truncating it or summarising it. Until ADR-0221
                this field carried one of sixteen constant phrases and the reply was
                stored nowhere; ``disposition`` is where that fact went.
            disposition: What became of the pass, as a member of a closed vocabulary
                (ADR-0221 §2). **Handed to capture, not computed here** — capture
                judges nothing (§4), and which member a pass reached is the engine's
                to say. ``None`` only where a caller records an exchange this system
                did not drive; the three render sites read this field first and fall
                back to ``outcome``, so a record carrying a member has its ``outcome``
                rendered into no model prompt (§3).
            parked: The binding this turn parked on, where it parked, so a
                recovered resumption can find its way back to this conversation.
            supplied_withheld: Whether content ADR-0199 §3 withholds from a
                channel of unbounded audience stood in the warrant of the turn whose
                rendering ``content`` carries (ADR-0204 §2, whose evaluation ADR-0217
                §3 leaves unchanged). **Handed to capture, not computed here** —
                capture judges nothing (§4), and this is the pipeline's evaluation
                exactly as ``content`` is the pipeline's rendering. What the episode
                *records* is ADR-0217 §1's placement: ``True`` here writes reach
                ``OWNER`` with setter ``DERIVED``, and ``False`` writes the default.
                ``False`` where no turn produced the rendering at all: a routed pass
                and a resumption recovered from durable state each carry no goal
                statement and no plan rationale of any turn, so there is nothing in
                their episode for a narrowing to be about.
            modality: How the user material this episode renders reached this system
                (ADR-0221 §5). **Handed to capture, not computed here**, for
                ``supplied_withheld``'s own reason and at the same sites: the value
                "belongs to the user material the episode renders, not to the pass
                that performs the capture and not to the conversation", so the
                resolution of a parked step carries the *parked* turn's value and this
                method can no more derive it than it can derive ``content``. It says
                nothing about the assistant's own contributions to the record — not
                the plan rationale in ``content``, not the reply in ``outcome``.
            derived_from_external: Whether the supply the turn ran over held a record
                resting on recorded external content (ADR-0223 §1) — the disjunction
                of ``rests_on_recorded_external_content`` over what that turn
                selected, which is the same boolean the pass handed the egress seam
                (§2). **Handed to capture, not computed here**, for
                ``supplied_withheld``'s own reason and at the same sites: this stage
                holds no supply, reads no record and evaluates no predicate over any
                selection, so "capture judges nothing" holds for this field too.
                ``False`` where the pass carried no turn — a routed pass, a routed
                park's resolution and a resumption recovered from durable state — and
                it is true of what those episodes hold rather than a default they
                fall back on (§3). A ``True`` says *the supply this turn ran over held
                a record whose recorded origin is external*; a ``False`` says *no
                record in that supply carried the marker*, never *no external content
                was involved* (§7).
            delivery: What is known about this turn's spoken answer having been
                played, written onto the index row this allocates (ADR-0205 §4).
                ``converse_spoken`` supplies ``SpokenDelivery(state=UNKNOWN)`` —
                unconditionally, the park, the absent reply and the degraded
                synthesis included, because at capture the hub has produced an answer
                and knows nothing about what reached anyone. Every other operation
                supplies ``None``, and an absent value is never read as delivered and
                never read as heard.

        Returns:
            What became of the record. Never raises for a store failure: capture
            degrades a turn rather than failing it, because failing would throw
            away an answer the user already has.
        """
        try:
            # The clock reading is **inside** the boundary, not above it. A
            # non-conforming reading is a capture failure like any other, and by
            # this point the turn's answer already exists — raising here would
            # throw it away because the record of it could not be written, which
            # is the outcome §3 explicitly rejects. Nothing has been written when
            # it fails, so it degrades exactly as a refused append does.
            turn = await self._conversations.append(
                conversation_id, occurred_at=self._now(), parked=parked, delivery=delivery
            )
        except ConversationStoreError:
            # A refused append needs no compensation, because nothing was written:
            # the intent comes first and the store mints the episode id inside it,
            # so a capture whose append is refused never received an id and never
            # reached the memory store. This is the ordering paying for itself.
            _log.warning("conversation_capture_degraded", stage="append", exc_info=True)
            return CaptureReport(conversation_id=conversation_id, degraded=True)

        # ADR-0225 §2: between the index entry and the episode. `archived` is what
        # the verification below needs — it compensates an entry that landed, on
        # every path including the one where the episode write then fails, because
        # that path now has something to compensate where before it had nothing.
        archived = await self._archive_turn(
            turn, asked=asked, outcome=outcome, disposition=disposition
        )
        degraded = self._archive_owed(disposition) and not archived

        # The turn and the episode recording it carry **one** instant: the reading
        # rides back on the turn rather than being taken twice, so no clock
        # adjustment between the two writes can make them disagree.
        episode = self._episode(
            turn,
            content=content,
            outcome=outcome,
            disposition=disposition,
            now=turn.occurred_at,
            supplied_withheld=supplied_withheld,
            modality=modality,
            derived_from_external=derived_from_external,
        )
        try:
            await self._memory.write_atomic(
                [MemoryWrite(record=episode, mode=MemoryWriteMode.INSERT_IF_ABSENT)]
            )
        except MemoryStoreError:
            # The turn keeps its index entry and the transcript shows a gap at that
            # ordinal. Propagating instead would turn a delivered answer into a
            # failed turn; rolling the index entry back would lose the only durable
            # record that the exchange happened at all.
            _log.warning("conversation_capture_degraded", stage="episode", exc_info=True)
            if not archived:
                # The **id is still reported**, degraded though the capture is
                # (ADR-0205 §1): the index row landed and it is what carries the
                # delivery, so a device reporting on this turn later reaches a row
                # that exists. What did not land is the episode, which every reader
                # already renders as a gap. Nothing was written that a compensation
                # could reach, so this path still returns without verifying.
                return CaptureReport(
                    conversation_id=conversation_id, episode_id=turn.episode_id, degraded=True
                )
            # ADR-0225 §2: the verification runs whenever **either** write landed.
            # An archive entry stands at this address, so a conversation stamped
            # underneath this capture has something to compensate here that it did
            # not have before.
            return await self._verify(turn, wrote_episode=False, wrote_entry=True, degraded=True)

        return await self._verify(turn, wrote_episode=True, wrote_entry=archived, degraded=degraded)

    async def record_delivery(
        self, conversation_id: str, report: SpokenDeliveryReport
    ) -> ConversationTurn | None:
        """Apply one device's report to the turn it names (ADR-0205 §1, §3).

        **One store call and no sequence**, which is why this is short: the store
        owns all three of §3's conditions and decides them under its own
        per-conversation exclusion, so there is nothing here to compose and nothing
        for a caller to re-derive. It sits on this stage rather than on the engine
        because this stage is where the ``ConversationStore`` handle lives.

        **A benign miss is discarded rather than raised** (§1). A report naming a
        turn this conversation does not carry — an index entry deleted or reclaimed,
        an id belonging to another conversation, a turn already stamped — performs
        nothing and returns ``None``, and the call that carried it goes on: a benign
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
            The turn as stamped, or ``None`` where nothing was stamped.

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
            return None

    def _archive_owed(self, disposition: ExchangeDisposition | None) -> bool:
        """Whether this capture owes the archive an entry at all (ADR-0225 §6, §10).

        Two conditions and no others: the archive is switched on, and the caller
        supplied a disposition. A caller that supplies none is recording an exchange
        this system did not drive, and the archive holds what this system's own
        capture recorded.
        """
        return self._archive_enabled and disposition is not None

    async def _archive_turn(
        self,
        turn: ConversationTurn,
        *,
        asked: str | None,
        outcome: str | None,
        disposition: ExchangeDisposition | None,
    ) -> bool:
        """Write this turn's transcript entry; report whether one landed (§1, §2).

        **The entry is built from values handed here and from no rendering** (§1).
        ``asked`` is the user's own words as the call site threaded them, ``outcome``
        is the composed reply this capture is already storing whole, and no part of
        ``content`` reaches the archive: not the plan rationale, not the confirmation
        line, not the tool line.

        The address is the episode's own id, which
        :meth:`~ai_assistant.core.protocols.ConversationStore.append` derived and
        returned on the turn (§3) — this stage mints nothing and predicts nothing —
        and the conversation and ordinal ride along as §1's grouping fields.

        Returns:
            Whether an entry now stands at this turn's address. ``False`` where none
            was owed, and ``False`` where the write failed — the caller distinguishes
            the two through :meth:`_archive_owed`, because only the second degrades
            the capture.

        Never raises. §2's "never fails a turn and never fails a capture" is
        unconditional, so a value the archive's own model refuses degrades this
        capture exactly as a store fault does rather than propagating.
        """
        if not self._archive_owed(disposition):
            return False
        try:
            entry = TranscriptEntry(
                address=turn.episode_id,
                conversation_id=turn.conversation_id,
                ordinal=turn.ordinal,
                occurred_at=turn.occurred_at,
                asked=asked,
                replied=outcome,
                # Narrowed by `_archive_owed` above, which is what `disposition is
                # not None` there buys: the field is required and carries no `None`
                # (§10).
                disposition=disposition,  # type: ignore[arg-type]
            )
            await self._archive.append(entry)
        except TranscriptArchiveError, ValidationError:
            # §2: never fails a turn, never fails a capture, never retried. Logged
            # rather than swallowed, and the address is what the log carries — an
            # entry's text reaches no log, trace or audit trail (§4, ADR-0004 §5).
            #
            # **The construction is inside the guard, and `ValidationError` beside
            # the store fault.** §2's clause is that the archive write never fails a
            # capture, and a refusal from the *model* is a way for it to fail one:
            # every value here reaches this method already typed, but "already typed"
            # is a property of the callers rather than of this line, and the failure
            # it would produce is the exact outcome §2 rules out — a delivered answer
            # thrown away because the record of it could not be built. It degrades
            # like any other archive failure and is reported the same way.
            _log.warning(
                "conversation_capture_degraded",
                stage="archive",
                address=turn.episode_id,
                exc_info=True,
            )
            return False
        return True

    async def _verify(
        self,
        turn: ConversationTurn,
        *,
        wrote_episode: bool,
        wrote_entry: bool,
        degraded: bool,
    ) -> CaptureReport:
        """Destroy what this capture wrote if its conversation is gone (§8).

        §8's compensation has exactly one trigger, the one the ordering cannot rule
        out: an append that *succeeded* before the conversation was stamped, whose
        writes land after. ADR-0225 §2 widens what it destroys rather than when it
        runs: the archive entry at that address goes too, so a conversation the user
        deleted mid-capture leaves neither an episode nor a transcript.

        **The archive entry is discarded first**, on §5's rule that the residue of a
        partial failure must be the one the user can still reach and destroy: the
        other order would leave retained text after a deletion the user was told
        succeeded.

        Args:
            turn: The index row this capture allocated.
            wrote_episode: Whether the episode write landed, so there is one to
                compensate. ``False`` on the path where it raised.
            wrote_entry: Whether an archive entry landed, likewise.
            degraded: What this capture already knows about itself — a failed archive
                write, which §2 reports here and which a standing conversation does
                not clear.
        """
        try:
            standing = await self._conversations.get(turn.conversation_id)
        except ConversationStoreError:
            # We cannot tell whether to compensate. The writes went in and, absent
            # evidence otherwise, they stand — so the turn is **not** reported as
            # unrecorded, which would be a false alarm. A conversation that was in
            # fact stamped still has its tombstone, and the next sweep destroys this
            # episode and this entry through it.
            _log.warning("conversation_capture_unverified", stage="verify", exc_info=True)
            return CaptureReport(
                conversation_id=turn.conversation_id,
                episode_id=turn.episode_id,
                degraded=degraded,
            )
        if standing is not None:
            return CaptureReport(
                conversation_id=turn.conversation_id,
                episode_id=turn.episode_id,
                degraded=degraded,
            )

        if wrote_entry:
            try:
                await self._archive.discard(turn.episode_id)
            except TranscriptArchiveError:
                _log.warning(
                    "conversation_capture_compensation_failed",
                    stage="archive",
                    address=turn.episode_id,
                    exc_info=True,
                )
        if wrote_episode:
            try:
                await self._memory.delete(turn.episode_id)
            except MemoryStoreError:
                # §9.6: the turn still returns its answer and the failure is reported
                # rather than swallowed. What is left is an orphan the tombstone's own
                # sweep will find, for as long as the grace holds.
                _log.warning("conversation_capture_compensation_failed", exc_info=True)
        return CaptureReport(conversation_id=turn.conversation_id, degraded=True)

    def _episode(  # noqa: PLR0913 — the turn, the rendering, the reply, what became of the pass, the instant both writes share, the disclosure evaluation, the modality and the origin mark; every one is a distinct fact about the turn being recorded
        self,
        turn: ConversationTurn,
        *,
        content: str,
        outcome: str | None,
        disposition: ExchangeDisposition | None,
        now: datetime,
        supplied_withheld: bool,
        modality: Modality,
        derived_from_external: bool,
    ) -> EpisodicMemory:
        """Build the one ``EpisodicMemory`` a turn deposits (§4).

        **Capture judges nothing.** ``importance`` stays at its default, because
        importance is a judgement and salience is leg 7's decision, not a number the
        recorder invents. ``participants`` stays empty, because the two parties to a
        turn are structural rather than informative and constants there would
        occupy, with noise, the field an observer means to fill with the people an
        episode is *about*. ``validity`` stays fully open, because nothing retires
        an episode: supersession is a law about beliefs that contradict each other,
        and two things that both happened never do. ``evidence`` stays empty: §3's
        obligation to cite binds a *proposal of a belief*, and an episode is the
        terminal citation — the thing other records cite — so requiring it to cite
        something would demand a regress.

        ``OBSERVED`` places every captured episode in the ``DERIVED`` band, which
        makes capture the first producer into it, arriving before the observer it
        exists to feed.

        **``last_confirmed_at`` stays unset, and that is a decision rather than an
        omission** (ADR-0109 §4). ADR-0103 §9's derived rule ranges over the
        episodes a record *cites*, and this one cites nothing by the paragraph
        above, so over the empty set it yields nothing and the record reads as
        ADR-0103 §9's **unknown**. That is the honest answer: an episode records
        that something happened, nothing retires it, and "is this still true?" is
        not a question about it. Writing ``occurred_at`` into the field instead
        would make every episode in the store claim a currency it has no use for.

        **``placement``, ``disposition``, ``capture`` and the provenance's origin mark
        are the four fields this method neither defaults nor decides** (ADR-0204 §2,
        ADR-0217 §1, ADR-0221 §2 and §5, ADR-0223 §1). Each is stamped from a value the
        pipeline computed and carried here,
        so "capture judges nothing" holds exactly as it does for ``content``: this
        method reads no record, no supply and no channel, and every other field
        ADR-0074 §4 fixes is stamped as it always was. What ``placement`` writes is
        ADR-0217 §3's **derivation** — reach ``OWNER``, setter ``DERIVED`` — and never
        an act or a proposal, neither of which this producer can make.

        **``outcome`` now carries the composed reply and ``disposition`` carries what
        became of the pass** (ADR-0221 §1, §2). Both are the caller's values, written
        here unexamined: this method does not inspect the reply for a Tier 0 value and
        no implementation adds such an inspection on this path (§7), because the
        reliance is residency — Tier 0 secrets live in the OS keyring, are read
        through ``SecretStore`` by ``models/`` and ``tools/`` alone, and are in no
        record, facet, plan or step account the composing stage is given (ADR-0004
        §3).

        **``capture`` is built here from the modality the pipeline passed**, exactly as
        ``placement`` is built from its boolean. What ADR-0221 §5 fixes is that the
        value belongs to the user material the episode renders — so a resolution
        carries the parked turn's, and this method is handed the answer rather than
        deriving one.

        **``provenance.derived_from_external`` is stamped from the value the pipeline
        threaded** (ADR-0223 §1, partially superseding ADR-0221 §6's first sentence).
        It is the disjunction of ``rests_on_recorded_external_content`` over the
        records the turn whose rendering this episode carries actually selected —
        computed once per pass by the component that made the selection, and carried
        here as data exactly as ``content`` is. This method evaluates no predicate,
        holds no supply and reads no record to obtain it, and a capture site with no
        turn to thread from states ADR-0223 §3's third case in code rather than
        falling back on a default.

        **What the mark says, and what no reader may make it say** (ADR-0223 §7,
        inheriting ADR-0098 §5 and ADR-0106 §1 verbatim). A ``True`` says *the supply
        this turn ran over held a record whose recorded origin is external*. A
        ``False`` says *no record in that supply carried the marker* — never *no
        external content was involved*, and never *nothing external influenced this
        exchange*. Nothing here detects external content embedded in text whose
        recorded origin is not external, and no lane cites ADR-0223 as authority that
        it does or that ADR-0098 §5's corridor has narrowed.

        **The instant is this turn's own**, which is ADR-0217 §1's producer
        obligation discharged at the one site that can: "every derivation this system
        performs writes the instant of the narrowing it makes", so that an untimed
        ``DERIVED`` placement found in a store is diagnostic of §9's decode of a
        pre-field record rather than of a producer that forgot. The turn's
        ``occurred_at`` is the reading this method already carries, so the narrowing
        and the record of it cannot disagree about when the turn happened.
        """
        return EpisodicMemory(
            id=turn.episode_id,
            content=content,
            occurred_at=turn.occurred_at,
            outcome=outcome,
            disposition=disposition,
            capture=Capture(modality=modality),
            expires_at=None if self._retention is None else now + self._retention,
            provenance=Provenance(
                source=MemorySource.OBSERVED,
                confidence=CAPTURE_CONFIDENCE,
                last_updated=now,
                derived_from_external=derived_from_external,
                # `last_confirmed_at` left at its `None` default — see above.
            ),
            placement=(
                Placement(reach=PlacementReach.OWNER, set_by=PlacementSetter.DERIVED, set_at=now)
                if supplied_withheld
                else Placement()
            ),
        )

    # --- deletion (§8) -------------------------------------------------------

    async def digest(self, conversation_id: str) -> ConversationDigest | None:
        """The count and span a deletion ceremony shows, or ``None`` (§8).

        Two reads and no walk: the record for the span, and the *tail* turn for the
        count, whose ordinal **is** the count because ordinals are dense from
        :data:`~ai_assistant.core.types.FIRST_TURN_ORDINAL` and rows leave only when
        the whole record is dropped. ADR-0073 §7 declined a turn count on the record
        for want of a consumer and noted it is derivable from the ordinal; this is
        that consumer, deriving it.

        Returns:
            The digest, or ``None`` when the id names nothing or names a
            conversation already stamped deleted — a surface must not show, or take
            consent for, something it cannot display.

        Raises:
            ConversationStoreError: If the index cannot be read.
        """
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            return None
        tail = await self._conversations.turns(conversation_id, limit=1)
        return ConversationDigest(
            id=conversation.id,
            started_at=conversation.started_at,
            last_turn_at=conversation.last_turn_at,
            recorded_turns=tail[-1].ordinal if tail else 0,
        )

    async def delete(self, conversation_id: str) -> bool:
        """Destroy a conversation: stamp, purge, drop (§8, ADR-0004 §6).

        The three steps normally run to completion here, and the tombstone is what
        makes a crash survivable rather than final. If this process dies at any
        point — or a racing capture writes its episode after step 2 — the stamped
        record and its index are still there, still naming every episode id
        involved, and :meth:`sweep_deletions` finishes it.

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

        Idempotent by re-walking: nothing removes an index row until the record is
        dropped, so a run that dies part-way is re-run from the beginning and every
        delete it repeats is a no-op on an id already gone.

        **The archive discard is the first action of §8's step 2** (ADR-0225 §5),
        before any episode is deleted, on the rule §5 draws from ADR-0074 §8's own
        third mitigation: the residue of a partial failure must be the one the user
        can still reach and destroy. A crash after it leaves *records* present, which
        ``forget`` and this very sweep destroy on the next attempt; the other order
        would leave retained text after a deletion the user was told succeeded.

        **A discard that raises aborts the call here, and no clause of §8 changes.**
        Every episode the index names still resolves, so step 3's own condition is
        unmet by §8's own terms — the tombstone survives and the reclaim re-runs the
        whole of step 2, this discard included, in the deleting call, at engine start
        and later on the hub's schedule. No third conjunct is added to step 3.

        **A second run finding the archive already empty is the conforming answer.**
        ``discard_conversation`` destroys what it matches or nothing and returns zero
        for a conversation with no entries (ADR-0225 §5), so the run that follows a
        ``MemoryStore.delete`` failure part-way through step 2 carries the remaining
        episode deletions through to the drop rather than treating the zero as an
        error.

        Returns:
            Whether the record was dropped. ``False`` while the grace still holds —
            the tombstone is deliberately kept alive past the deletion so a capture
            that commits and then dies is still swept.

        Raises:
            TranscriptArchiveError: If the transcript could not be destroyed. Nothing
                below runs, and the tombstone stands.
        """
        await self._archive.discard_conversation(conversation_id)
        cursor: str | None = None
        while True:
            batch = await self._conversations.episodes_to_purge(conversation_id, after_id=cursor)
            if not batch:
                break
            for episode_id in batch:
                await self._memory.delete(episode_id)
            cursor = batch[-1]
        return await self._conversations.drop_if_eligible(conversation_id)

    # --- retention reclaim (§7) ---------------------------------------------

    async def reclaim(self) -> int:
        """Drop the index of conversations that are empty and idle (§7).

        **This sweep never destroys an episode.** Episodes leave on their own
        ``expires_at``, stamped at capture from the horizon in force when they were
        written; this only *observes* — it asks the ``MemoryStore`` whether any turn
        still resolves — and drops a conversation record when none does. Stated as
        one sequence with the deletion sweep, a live episode would be destroyed
        because its *conversation* was old, and a record stamped under a 30-day
        horizon would die under a later 7-day setting it was never written against.

        A conversation is reclaimable when it has **no live turns and** its
        ``last_active_at`` is past the horizon — both, not the first alone. With
        only the first, a conversation whose single turn expired would be dropped
        while its owner still held a working id.

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
        """Whether **no** turn of this conversation still resolves to an episode.

        The half of the reclaim precondition ``ConversationStore`` cannot answer
        (golden rule 1). It walks every batch, because an implementation that
        inspected only the first would let the record be dropped while live
        episodes sat behind it — and it stops at the first episode that *does*
        resolve, since one live turn already settles the question and reclaim
        destroys nothing it walks past.
        """
        cursor: str | None = None
        while True:
            batch = await self._conversations.episodes_to_purge(conversation_id, after_id=cursor)
            if not batch:
                return True
            for episode_id in batch:
                if await self._memory.get(episode_id) is not None:
                    return False
            cursor = batch[-1]

    # --- the composed export (§9) -------------------------------------------

    async def export(self) -> DataExport:
        """Assemble the export a user receives (§9, ADR-0004 §6).

        A ``ConversationTurn`` outlives its episode: the row survives expiry and
        deletion, carrying an ordinal, an occurrence time and a derived episode id.
        Handing those rows over would say *that* an exchange happened and *when*,
        for content the artifact cannot show — leaking when the user was talking
        and how often. So a turn whose episode does not resolve is skipped, and a
        conversation that had turns and has none left is dropped with them.

        **The filter's source of truth is the artifact, not the store.** The
        conversation half is filtered against the memory half of *this* export
        rather than against a live read, which is what makes the result internally
        consistent without a transaction spanning the two stores: no turn can
        dangle, because the thing it is checked against cannot move underneath it.

        A conversation that never had a turn is **kept**. The rule §9 states is
        about a conversation "whose episodes have all expired" exporting as nothing
        rather than as an empty shell with a timeline; a conversation that never
        recorded one has no timeline to leak, and the store's own contract already
        holds that an empty conversation is state the user holds.
        """
        memories = tuple(await self._memory.export())
        snapshot = await self._conversations.export()
        live = {record.id for record in memories}

        turns = tuple(turn for turn in snapshot.turns if turn.episode_id in live)
        indexed = {turn.conversation_id for turn in snapshot.turns}
        surviving = {turn.conversation_id for turn in turns}
        conversations = tuple(
            one for one in snapshot.conversations if one.id in surviving or one.id not in indexed
        )
        return DataExport(
            memories=memories,
            conversations=snapshot.model_copy(
                update={"conversations": conversations, "turns": turns}
            ),
        )

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
    "AssembledHistory",
    "CaptureReport",
    "ConversationDigest",
    "ConversationLifecycle",
    "DataExport",
]

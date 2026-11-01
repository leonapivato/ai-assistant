"""The canonical fake for :class:`~ai_assistant.core.protocols.AssistantEngine`.

``CONTRIBUTING.md`` -> "Adding a Protocol" makes a canonical fake one third of the
triad, and ADR-0087 §6 says what makes *this* one load-bearing rather than
convenient: it is the **second implementation** of the engine surface, arriving in
ADR-0084 §5's change 3 — before the hub, before the `wire` package, before any
client. §4 of ADR-0084 rules that the size limit is a clause "*every*
implementation enforces", with "the conformance suite … what holds them to it", so
this fake and the concrete
:class:`~ai_assistant.orchestration.engine.Engine` are the first two things ever
held to it together.

**It is a working in-memory engine rather than a recorder**, and that is
deliberate. A double that answered every call with a scripted value could satisfy
a suite while enforcing none of the five clauses ADR-0085 states over behaviour —
the page-size default, identifier validation and normalisation, pre-``await``
materialisation of the filters, local refusal of a malformed page argument, and
the size limit in both directions. Here ``learn`` really stores a belief,
``beliefs`` really pages it, ``forget`` really destroys it, so the suite can
exercise those clauses end to end against a subject it can also set up cheaply.

**It has no lifecycle, and that is the point of ADR-0083 §8.** There is no
``start`` and no ``aclose``: they are not on the Protocol, because a client that
could call ``aclose()`` could shut down the hub from a spoke. An implementation
without a lifecycle does not have to invent one to conform, and this is the
evidence that the Protocol really does leave it out.

Every scriptable behaviour is a plain attribute rather than a constructor
argument, so a test changes one thing without restating the rest.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from base64 import b64encode
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, assert_never
from uuid import UUID, uuid4

from ai_assistant.core.channel_validation import snapshot
from ai_assistant.core.device_context import current_requesting_device
from ai_assistant.core.episode_encoding import check_detail, check_list
from ai_assistant.core.errors import (
    ActivationStoppedError,
    ConversationStoreError,
    GrantError,
    InvalidGrantError,
    MemoryStoreError,
    ModelTimeoutError,
    NotificationBudgetError,
    OversizedValueError,
    StoryStoreError,
    UngrantableSourceError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    OWNER_PERSON_ID,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEnding,
    ActivationStop,
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ConversationDigest,
    ConversationSummary,
    EpisodeCaptureReport,
    EpisodeChunk,
    EpisodePage,
    EpisodicMemory,
    EvidenceItemPart,
    GrantableSource,
    GrantScope,
    InformationalEventResult,
    InputPart,
    LegacyPart,
    Memory,
    MemoryKind,
    MemoryOperation,
    MemoryOperationKind,
    MemorySource,
    MemorySupport,
    MemoryWriterName,
    MessageAuthor,
    NewMessage,
    NotificationDelivery,
    PendingCandidate,
    PermissionDecision,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingStatus,
    Provenance,
    RecordedInvocation,
    RememberCallPart,
    SendOutcome,
    SourceGrant,
    SpendTotal,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenRendering,
    SpokenReply,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StoryNoteId,
    StoryOutcome,
    SupportDirection,
    SupportOrigin,
    SupportPart,
    TextChannelPayload,
    WholeTextReply,
    approval_choice,
    belief_view,
    chat_conversation_ids,
    check_chat_cursor,
    check_chat_position,
    check_story_page,
    checked_chat_devices,
    describe_untrusted,
    encodable_text,
    episode_view,
    person_model_lists,
    profile_field,
    profile_value,
    secret_value,
    stamped_support,
    story_members,
    story_move_members,
    story_note_ids,
    story_note_text,
    user_message,
)
from ai_assistant.orchestration import person_panel
from ai_assistant.orchestration.candidates import held_candidates
from ai_assistant.orchestration.change_stream import Activity, ChangeStream
from ai_assistant.orchestration.channels import (
    UNCAPTURED,
    ChannelProjection,
    captured_result,
)
from ai_assistant.orchestration.chat import (
    ChatInput,
    ChatReader,
    ChatWriter,
    couldnt_finish,
)
from ai_assistant.orchestration.conversations import (
    check_devices_fit,
    check_message_fits,
    conversation_state,
    episode_conversation,
    episodes_on_place,
    fit_changes,
    fit_transcript,
)

# ADR-0206 §3's placement is **named rather than copied**, exactly as ADR-0087 §7
# requires of the payload encoder above: "the canonical fake reaches for this one rather
# than growing a second copy to keep in step by hand". A re-declared triple here would be
# a second disclosure rule that drifts silently — the fake would certify a consumer
# against a hub that speaks a different set of notifications, which is the one thing
# this package may not do, and is the drift golden rule 1 exists to prevent rather than
# an instance of it. `lint-imports` holds the boundary that rule is enforced by, and
# `ai_assistant.testing` is test-only rather than a runtime subsystem.
from ai_assistant.orchestration.disclosure import notification_is_speakable
from ai_assistant.orchestration.engine import (
    approval_panel,
    episode_card_facts,
    tap_on_approval_panel,
)
from ai_assistant.orchestration.episode_reads import fit_chunk, fit_page
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    check_arguments,
    check_keyless_call,
    check_payload,
    check_provisioning_call,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
)
from ai_assistant.orchestration.stories import (
    fitted,
    owner_summary,
    resolved_view,
    unknown_activation,
)
from ai_assistant.orchestration.story_standing import OWNER_READER
from ai_assistant.orchestration.story_standing import story_standing as standing_of
from ai_assistant.testing.activation import FakeActivation
from ai_assistant.testing.connections import FakeConnectionProvisioner
from ai_assistant.testing.conversations import FakeConversationStore
from ai_assistant.testing.memory import FakeMemoryStore
from ai_assistant.testing.notifications import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)
from ai_assistant.testing.permissions import FakeAuditTrail
from ai_assistant.testing.planning import FakePlanStore
from ai_assistant.testing.reads import FakeSourceReadTrail
from ai_assistant.testing.stories import FakeStoryStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Sequence

    from ai_assistant.core.protocols import AuditTrail, SourceReadTrail, SpendLedger
    from ai_assistant.core.types import (
        ApprovalChoice,
        ApprovalPanel,
        ApprovalPanelTap,
        ApprovalRequest,
        ChatChanges,
        ChatDevice,
        ChatStreamChunk,
        ChatStreamEnd,
        ConnectedAccount,
        ConnectionAct,
        EncodableText,
        HeldNotification,
        Identifier,
        MessageReceipt,
        NonBlankEncodableText,
        NotificationPreferences,
        PersonModelEdit,
        PersonModelList,
        PersonModelView,
        ProfileChange,
        ProfileField,
        ReplyCapability,
        SecretValue,
        SourceReadRecord,
        StoryHeader,
        StoryLogPage,
        StoryNoteOutcome,
        StoryPage,
        StoryStanding,
        StorySummaryView,
        StoryView,
        TranscriptPage,
        UserMessage,
    )
    from ai_assistant.orchestration.approval_calls import CardFacts
    from ai_assistant.orchestration.person_block import PersonBlocks

#: A fixed instant, so a fake engine's output is deterministic without a clock.
_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: How far each activity stamp advances per event. A logical clock rather than a
#: real one: it keeps the ordering deterministic and keeps the fake free of a wall
#: clock.
_TICK = timedelta(seconds=1)

#: The confidence a stored belief is held at here. Below 1.0 so a
#: ``DERIVED``-banded record would still validate, and unadjusted because nothing
#: in this fake loses evidence.
_CONFIDENCE = 0.9


def _check_positive_int(value: int, *, name: str) -> None:
    """Refuse a constructor knob that is not a positive integer.

    The concrete engine's guard, in its words and with its classes, because ADR-0084
    §4's substitutability runs in **both** directions: a double admitting a
    configuration no engine admits lets a consumer's tests pass over one production
    cannot be built into, and a double refusing the same value as a different class
    makes the two disagree about what kind of failure it is — the half a positivity
    check on its own leaves open. Unrefused, the value surfaces later and as
    something else: ``1.5`` bounds a retention at two, ``0`` discards from an empty
    table on the first settlement, and ``float("nan")`` as a byte limit compares
    ``False`` against every ``>``, so nothing is ever over it.

    **The exact ``int``, allowlisted**, and the untrusted value described through
    :func:`describe_untrusted` rather than ``repr`` — both for the reasons the
    concrete engine's guard states at length, and here for one more: whichever of the
    two a consumer tests against, the class it must handle has to be the same one
    (ADR-0084 §4). An ``int`` subclass overriding its comparisons would make a byte
    limit non-binding on the double exactly as it would on the engine, and a hostile
    ``__repr__`` would replace the documented ``TypeError`` with its own exception on
    the double exactly as it would there.

    Args:
        value: The knob as the caller passed it.
        name: The parameter's name, which is what the refusal names.

    Raises:
        TypeError: If it is not an exact ``int`` — ``bool`` included, since it is an
            ``int`` subclass and a flag is neither a count nor a byte bound, and
            every other subclass with it.
        ValueError: If it is not positive.
    """
    if type(value) is not int:
        msg = f"{name} must be an integer, got {describe_untrusted(value)}"
        raise TypeError(msg)
    if value < 1:
        msg = f"{name} must be positive, got {value}"
        raise ValueError(msg)


class FakeAssistantEngine:
    """An in-memory :class:`~ai_assistant.core.protocols.AssistantEngine`.

    **It reaches for `orchestration.payloads` rather than growing its own
    encoder**, and ADR-0087 §7 is what makes that safe: conformance to the
    canonical encoding is defined by *output*, so "two encoders may exist without
    the contract weakening" — and one encoder cannot make two implementations
    disagree about which calls are refused, which is the property change 3 needs.
    ADR-0084 §6 places the codec in the `wire` package, which does not exist yet,
    and ADR-0085 §8c forecloses a ``core``-owned one; where the encoder finally
    lives is ADR-0087 §9's open question and change 4's to answer.
    """

    def __init__(
        self,
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        chat_reader: bool = True,
    ) -> None:
        """Create an engine holding nothing.

        Args:
            max_payload_bytes: The contract limit ADR-0085 §8c declares, in bytes.
                A conformance test sets it small so the boundary is cheap to reach;
                the default is ADR-0084 §3's 16 MiB frame size less §8b's 512-byte
                envelope reserve, which is what a deployment gets by saying nothing.
                Guarded exactly as the concrete engine guards it, for the reason
                below: a limit that cannot bind fails *open* across every argument
                check and every result check this double performs (#1686).
            chat_reader: Whether a message written into a conversation is answered
                (ADR-0293 §6, §10), as the engine's ``chat_reader`` says the same; the
                initial value of :attr:`chat_reader`.

        Raises:
            TypeError: If ``max_payload_bytes`` is not an **exact** ``int``. A
                ``bool`` is the named case — it is an ``int`` subclass, and a flag is
                not a count — and a ``float`` like ``1.5`` is refused rather than
                compared, which is the guard the concrete engine states in these
                words (:func:`_check_positive_int`).
            ValueError: If it is not positive.
        """
        # ADR-0085 §8c's limit, guarded on the concrete engine's terms, since every
        # argument check and every result check this double performs measures against
        # this one number (#1686).
        _check_positive_int(max_payload_bytes, name="max_payload_bytes")
        self._max_payload_bytes = max_payload_bytes
        #: The notification surface's whole state, public so a consumer can
        #: seed it: ``await engine.notification_store.admit(candidate,
        #: policy=engine.notification_policy)`` is how a held record gets
        #: here, there being no producer on this surface (ADR-0130 §1).
        self.notification_store = FakeNotificationStore()
        self.notification_policy = FakeNotificationPolicy()
        self.beliefs_held: dict[str, Belief] = {}
        self.episode_memory = FakeMemoryStore(now=lambda: _AT)
        #: The story store the nine story methods read and write (ADR-0289 §4),
        #: public so a consumer can seed or inspect it. The activation checks those
        #: methods make read :attr:`episode_memory`, which is where a consumer seeds
        #: the episodes a story's activation members name.
        self.story_store = FakeStoryStore(now=lambda: _AT)
        #: The plan store :meth:`pending_candidates` reads the observation records and
        #: effect records from, public so a consumer can seed or inspect it; the
        #: episodes it joins are :attr:`episode_memory`'s (ADR-0329 §3:3).
        self.plan_store = FakePlanStore(now=lambda: _AT)
        #: The instant the approvals panel reads its requests at and a panel tap is
        #: stamped with (ADR-0361 §4:6, §4:9), replaceable as :attr:`placement_clock` is.
        #: The requests are :attr:`plan_store`'s, and the episodes that asked
        #: :attr:`episode_memory`'s, where the card's facts are read.
        self.approval_clock: Callable[[], datetime] = lambda: _AT
        #: How many times a panel tap woke the Approvals channel's sensor: this fake has
        #: no sensor, so a wake is counted where the engine's would run (ADR-0361 §3:4).
        self.approvals_woken = 0
        #: The person-block assembly the eight person-model members answer from
        #: (ADR-0338 §8:1), as the engine's ``person_blocks`` is: ``None``, the default,
        #: is a hub with ``Settings.person_model`` off, where each member raises
        #: :class:`~ai_assistant.core.errors.PersonModelOffError` (§11:2). A consumer
        #: switches it on with a
        #: :class:`~ai_assistant.orchestration.person_block.PersonBlocks` over a
        #: :class:`~ai_assistant.testing.FakePersonModelStore` and
        #: :attr:`episode_memory`, where the memories its pins point at are held.
        self.person_blocks: PersonBlocks | None = None
        #: The placement each held belief carries (ADR-0217 §1), by record id. Held
        #: **beside** the beliefs rather than on them, because
        #: :class:`~ai_assistant.core.types.Belief` carries no placement: ADR-0217 §7
        #: obliges no surface to render one, so the inspection projection is unmoved
        #: and this table is what :meth:`guard` and :meth:`unguard` act on.
        #:
        #: An id absent here carries §6's default, which is what a fresh belief has.
        #: A consumer that wants an act refused seeds the entry a producer would have
        #: written — a ``DERIVED`` placement — because nothing on this surface derives
        #: one, there being no producer here.
        self.placements: dict[str, Placement] = {}
        #: What an act stamps its placement with (ADR-0217 §7). **Strictly
        #: increasing** by default, unlike :attr:`grant_clock`, because ADR-0217 §10
        #: pins that a second ``guard`` returns the first's value *instant included*
        #: — an arm a constant clock passes whether or not the act wrote a second
        #: time, and which is therefore only a test of the no-write rule while two
        #: writes would differ. Replaceable, so a consumer that wants a fixed stamp
        #: can have one.
        placement_ticks = count(1)
        self.placement_clock: Callable[[], datetime] = lambda: _AT + _TICK * next(placement_ticks)
        self.conversations_held: dict[str, ConversationDigest] = {}
        self._used_conversation_ids: set[str] = set()
        #: The chat space (ADR-0293): transcripts, devices, the change stream — the
        #: canonical conversation store, public so a consumer can seed or inspect it.
        #: It mints the id each conversation joins it under from
        #: :attr:`_joining`, so a conversation keeps the id :attr:`conversations_held`
        #: knows it by.
        #: The channel activations this fake is running, from admission to the end of
        #: their finalization: what a conversation's "working…" reads (ADR-0293 §8:2).
        self._running_activations: list[FakeActivation] = []
        #: Per conversation, how many activations started from it have ended and how many
        #: times episodes on its place were forgotten, as the engine counts them (§8:2).
        self._activation_turns: dict[str, int] = {}
        self._joining: list[str] = []
        self._joining_lock = asyncio.Lock()
        self.chat = FakeConversationStore(now=lambda: _AT, new_id=self._joining_id)
        self._in_chat: set[str] = set()
        self._conversation_ids = count(1)
        #: When each conversation was last active — set at creation and refreshed
        #: whenever a turn begins against it (ADR-0074 §2). Held beside the digests
        #: rather than on them because a
        #: :class:`~ai_assistant.core.types.ConversationDigest` is the deletion
        #: ceremony's shape and carries no activity stamp.
        self.activity: dict[str, datetime] = {}
        #: What this engine's synthesizer can produce (ADR-0206 §3).
        #: :meth:`next_notification` renders in the **first** member of ``plays`` this
        #: set also names; an empty intersection degrades the rendering, which is how a
        #: consumer reaches that shape without a seam of its own.
        self.spoken_formats: frozenset[SpokenAudioFormat] = frozenset(SpokenAudioFormat)
        #: Which conversation each captured episode was recorded in, by episode id.
        #: Every id is ``activation:<activation_id>``, fixed at admission
        #: (ADR-0283 §2), so membership is retained here rather than read off the id.
        self._episode_conversations: dict[str, str] = {}
        activation_ids = count(1)
        self.activation_id_factory: Callable[[], str] = lambda: str(
            UUID(int=next(activation_ids), version=4)
        )
        self._ticks = count(1)
        #: The grantable sources this engine holds, by declared identity, each
        #: mapped to its configured location or to ``None`` where it has none
        #: (ADR-0102 §6). Scriptable with :meth:`hold_source`, so a client's own
        #: refusal paths — a source with a location and one without, granted and
        #: ungranted — are all reachable from a test (ADR-0102 §12 item 3).
        self.sources_held: dict[str, str | None] = {}
        #: Every grant and revocation this engine recorded, in the order it
        #: recorded them. Both kinds live here, because revocation is an **append**
        #: and never a mutation (ADR-0097 §4).
        self.grants_recorded: list[SourceGrant] = []
        #: What stamps ``decided_at`` on a grant or a revocation. Scriptable, and
        #: **that is what makes ADR-0102 §3's second clause testable at all**: the
        #: case that distinguishes a stated liveness from a derived one is a
        #: revocation timestamped *earlier* than the grant it revokes, which
        #: ADR-0097 §4 permits explicitly — and no sequence of surface calls can
        #: produce it, because the engine reads the clock. A test hands over one
        #: that runs backwards.
        #:
        #: **Fixed rather than ticking**, unlike the conversation activity stamp: a
        #: grant's ``decided_at`` is not an ordering invariant of anything (ADR-0097
        #: §4 derives liveness from ``revokes`` alone and never compares two
        #: instants), so a fake that advanced it would be asserting a sequence the
        #: contract does not have — and would put every record at its own instant,
        #: which is exactly where ``recent``'s ``id`` tie-break stops being
        #: exercised.
        self.grant_clock: Callable[[], datetime] = lambda: _AT
        #: The delivery outbox this engine polls (ADR-0131 §3), so a client's
        #: tests can drive the long poll against a contract-correct queue rather
        #: than a stub that answers whatever they wanted.
        self.notification_outbox = FakeNotificationOutbox(records=self.notification_store)
        #: ADR-0131 §5a's ``hub_max_notification_budget``, as the ceiling this
        #: engine refuses a poll above. §5a's own default, so a fake is not looser
        #: than the contract it stands in for.
        self.max_notification_budget = timedelta(seconds=300)
        #: The connection surface's whole state (ADR-0151 §16 item 4), scriptable
        #: through the canonical provisioner fake's own switches: its ``entries``
        #: are the live records and the history, ``secrets.fail()`` makes a keyring
        #: write or deletion raise, and ``repeat_next_reference()`` makes the mint
        #: collide — so a client's own refusal paths are all reachable from a test.
        #:
        #: **A provisioner rather than a dictionary**, because ADR-0148 §6's three
        #: writes are what the interesting obligations are about: a fake engine
        #: that set an entry and returned would answer every listing correctly
        #: while exhibiting none of the partial outcomes ADR-0151 §7 exists to make
        #: reportable.
        self.connections = FakeConnectionProvisioner()
        #: The audit trail ADR-0186 §1's two reads relay, public so a consumer can
        #: seed it — ``await engine.trail.record(decision)`` is how a ruling gets
        #: here, there being no producer for one on this surface: ADR-0186 §4
        #: refuses a promoted ``record``, because a client that could append to the
        #: audit record of what was permitted could fabricate history.
        #:
        #: **A whole ``AuditTrail`` rather than a list of decisions**, and it is
        #: replaceable for the reason ADR-0186 §11 makes a shared suite case of:
        #: ``AuditTrail.export`` states **no** order, so the case separating an
        #: engine that sorts from one that relays needs a conforming trail
        #: exercising that freedom. A fake holding a bare list could only hand back
        #: what its own sort produced, and would pass that case while asserting
        #: nothing.
        audit = FakeAuditTrail()
        self.trail: AuditTrail = audit
        #: The ledger ADR-0194 §6's read relays, public and replaceable for the
        #: ``trail`` attribute's reason: the states that matter here — an
        #: indeterminate period, a configured ceiling, a zone whose day boundary is
        #: not midnight UTC — are all facts about the **producer's** configuration,
        #: and a fake holding a pair of pre-built ``SpendTotal`` values could only
        #: hand back what a test had already assembled. Seed it by replacing it with
        #: a ``FakeAuditTrail`` built with a currency, a ceiling and a zone, and by
        #: claiming and completing invocations through it.
        #:
        #: **A ``SpendLedger`` and never a ``SpendGate``** (ADR-0194 §5): this
        #: surface exposes no admission, and a fake offering one would let a
        #: consumer's test spend a budget through an adapter.
        #: **Replace it together with** :attr:`trail`, since one object carries
        #: both faces here as it does in the composition root: a fake whose two
        #: attributes were different objects would state totals over rows the
        #: decision reads cannot see.
        self.spend: SpendLedger = audit
        #: The source-read trail ADR-0186 §10's two reads relay, public and seeded
        #: the same way — ``await engine.reads.record(read)`` — and for the same
        #: reason: this surface has no producer for a row either, because a read is
        #: authored on the seam that gated it (ADR-0185 §5) and nothing a client can
        #: call appends one.
        #:
        #: **A whole ``SourceReadTrail`` rather than a list of records**, on the
        #: ``trail`` attribute's reason with one turned around. There the point was
        #: that ``AuditTrail.export`` states *no* order; here it is that
        #: ``SourceReadTrail.export`` states one — recording order — which a bare
        #: list could only reproduce by accident of append order rather than by a
        #: contract a suite can hold the surface to. Replaceable, so a case can
        #: substitute a conforming trail that logs its reads or fails on demand.
        self.reads: SourceReadTrail = FakeSourceReadTrail()
        #: Every call, in order, as ``(method, arguments)`` — so a test can assert
        #: what reached the engine without reaching into its state.
        #:
        #: **A provisioning call records its identity and never its credential**
        #: (ADR-0151 §6): this list is read by tests and printed by failures, and a
        #: secret in it would be a disclosure path through the test double.
        self.calls: list[tuple[str, dict[str, object]]] = []
        #: Whether a message written into a conversation is answered (ADR-0293 §6,
        #: §10). Public, so a case built on a fixture that made this engine for it can
        #: still turn the answering off before it writes: ``False`` leaves every
        #: written message recorded and waiting, so no assistant message lands in a
        #: transcript or the change stream behind the case's back.
        self.chat_reader = chat_reader
        #: ADR-0293 §6's reader and its writer. **The engine's own reader and
        #: writer** over this fake's chat space, so the reading — every message starts
        #: its own activation after the start wait, whatever runs, so several may run
        #: from one conversation at once (ADR-0349 §8:1) — and the bookkeeping are the
        #: engine's by construction rather than a copy kept in step by hand; what this
        #: fake supplies is the activation (:meth:`_read_in`), which writes a canned
        #: reply naming its input. Its reads are tasks held here, so none is collected
        #: mid-run.
        self._chat_reads: set[asyncio.Task[None]] = set()
        self._chat_writer = ChatWriter(conversations=self.chat, max_payload_bytes=max_payload_bytes)
        self._reader = ChatReader(
            conversations=self.chat,
            activate=self._read_in,
            spawn=self._spawn_read,
            closing=lambda: False,
            mint=self._chat_activation_id,
        )
        #: ADR-0298 §7: **the engine's own change stream** over this fake's chat space,
        #: as the reader is, so what a following device is sent — its as-of membership,
        #: the filter at sending, the snapshots fitted and the current state pushed —
        #: is the engine's by construction. The fake never shuts down, so its stream
        #: ends only when its caller closes it.
        self._change_stream = ChangeStream(
            chat=self.chat,
            running=self._activity,
            state_of=lambda conversation_id, running: conversation_state(
                self.episode_memory, conversation_id, running=running
            ),
            closing=lambda: False,
            tracked=lambda work: work,
            max_payload_bytes=max_payload_bytes,
        )

    # --- the two turn calls -----------------------------------------------

    async def receive(
        self,
        input: ChannelInput,  # noqa: A002 — contract spelling
        *,
        reply: SpokenReply | None,
        timeout: timedelta,  # noqa: ASYNC109 — contract budget
    ) -> ChannelResult:
        """Receive a channel input with the fake's scripted collaborators.

        The text conversational combination is refused, as the concrete engine
        refuses it (ADR-0293 §11).
        """
        return await self._receive(
            input, reply=reply, timeout=timeout, projection=ChannelProjection("receive")
        )

    async def _receive(
        self,
        input: ChannelInput,  # noqa: A002 — ADR-0274 names the public parameter
        *,
        projection: ChannelProjection,
        reply: SpokenReply | None,
        timeout: timedelta,  # noqa: ASYNC109 — contract budget
    ) -> ChannelResult:
        """Process the channel using the fake's existing scripted outcomes."""
        supplied, capability = snapshot(input, reply)
        check_payload(
            {"input": supplied, "reply": capability, "timeout": timeout},
            max_bytes=self._max_payload_bytes,
            subject=f"the arguments to {projection.method}()",
        )
        activation = FakeActivation.channel(supplied, capability, _AT)
        activation.identify(self.activation_id_factory)
        self._running_activations.append(activation)
        projection = ChannelProjection(projection.method, activation.report)
        result: ChannelResult | None = None
        failure: BaseException | None = None
        try:
            result = await self._dispatch_channel(supplied, capability, timeout, activation)
            # Output bounds are processing obligations even when no capture
            # envelope could be allocated and finalization must return early.
            self._check_channel_result(result, projection)
        except BaseException as exc:
            failure = exc
        try:
            report = await activation.finish(
                memory=self.episode_memory,
                conversations=self.conversations_held,
                allocate=lambda conversation: self._allocate_episode(conversation, activation),
                max_bytes=self._max_payload_bytes,
                failure=failure,
                check_output=lambda: self._check_channel_result(result, projection),
            )
        finally:
            self._ended(activation)
        self._commit_episode(activation, report)
        failure = _stopped_failure(activation, failure)
        target = supplied.target
        if (
            isinstance(target, ChannelIdentity)
            and target.channel_type == "informational_event"
            and isinstance(failure, Exception)
            and not isinstance(failure, OversizedValueError)
        ):
            # ADR-0313 §4:5: an event that cannot finish, or is stopped, returns how it
            # ended; its episode is classified by what ended it. A result the output
            # bound refuses raises as every result does: one naming the same channel
            # could not be returned either.
            ended = (
                ActivationEnding.STOPPED if activation.stopped else ActivationEnding.COULDNT_FINISH
            )
            answer = _event_result(target, ended)
            # Held to the output bound with its receipt reserved, as a returned result is
            # (ADR-0085 §8c): it is built after the dispatch's own check.
            self._check_channel_result(answer, projection)
            return captured_result(answer, report)
        if failure is not None:
            raise failure
        if activation.output_failure is not None:
            raise activation.output_failure
        assert result is not None  # noqa: S101 — a successful dispatch returned a value
        return captured_result(result, report)

    def _check_channel_result(
        self, result: ChannelResult | None, projection: ChannelProjection
    ) -> None:
        if result is not None:
            self._checked(projection.terminal(result), projection.method)

    async def _dispatch_channel(
        self,
        supplied: ChannelInput,
        capability: ReplyCapability | None,
        timeout: timedelta,  # noqa: ASYNC109 — caller processing budget
        activation: FakeActivation,
    ) -> ChannelResult:
        """Run an admitted event: admission refuses every other input (ADR-0313 §4:1)."""
        target = supplied.target
        assert isinstance(target, ChannelIdentity)  # noqa: S101 — admission refuses every other target
        assert target.channel_type == "informational_event"  # noqa: S101 — as above
        if timeout.total_seconds() <= 0:
            # ADR-0313 §4:5: the event's budget ran out before anything ran; the
            # call answers it with *couldn't finish* once the episode froze.
            raise ModelTimeoutError("the event's budget ran out before it was understood")
        activation.understand()
        self.calls.append(("receive", {"input": supplied, "reply": capability}))
        return _event_result(target, ActivationEnding.DONE)

    @staticmethod
    def _allocate_episode(conversation_id: str, activation: FakeActivation) -> str:
        """The address the activation's episode is written at (ADR-0283 §2).

        The id is the activation's own, ``activation:<activation_id>`` — the same value
        on every channel, so nothing here derives it from the conversation or a count.
        Nothing is recorded yet: :meth:`_commit_episode` does that once the insert has
        landed.
        """
        del conversation_id
        return f"activation:{activation.activation_id}"

    def _commit_episode(self, activation: FakeActivation, report: EpisodeCaptureReport) -> None:
        """Record a landed conversational episode in its conversation (ADR-0283 §7).

        **Only after the insert committed, and at once**, as ``record_turn`` follows the
        episode in production — before a stream yields its first chunk and before a
        processing failure is re-raised, so nothing the consumer does next can leave a
        landed episode outside its conversation's deletion. A capture that degraded — a
        colliding address the insert-if-absent write refused (§7:3) among them — moves
        no membership or digest, so forgetting its conversation cannot take
        another's episode. Membership is retained explicitly, standing in for the
        conversation's channel.
        """
        conversation_id = activation.conversation_id
        episode = report.episode_id
        if report.state != "recorded" or conversation_id is None or episode is None:
            return
        self._episode_conversations[episode] = conversation_id
        digest = self.conversations_held[conversation_id]
        self.conversations_held[conversation_id] = digest.model_copy(
            update={
                "recorded_turns": digest.recorded_turns + 1,
                "last_turn_at": _AT,
            }
        )

    async def stop_activation(self, activation_id: Identifier, /) -> ActivationStop:
        """Stop one running activation, as the engine does (ADR-0297 §3, §5).

        The fake holds its running channel activations in process, as the engine
        does, and a stop sets the mark of one whose end entry is not appended, in one
        synchronous step with that test; the pass then ends with the stop's end entry
        and a turn call awaiting it raises ``ActivationStoppedError``; a control
        activation (``resume``) is running from its admission to its finalization too,
        and a stopped one returns its outcome with ``stopped`` set and no reply. **It
        holds no plan store**, so no stop record is written: no claim this fake makes
        could be refused on one. Where none runs,
        an episode at ``activation:<activation_id>`` says it ran and ended, and no
        episode there says nothing ran that this fake knows of; neither writes
        anything.
        """
        named = identifier(activation_id, name="activation_id")
        check_arguments("stop_activation", max_bytes=self._max_payload_bytes, activation_id=named)
        self.calls.append(("stop_activation", {"activation_id": named}))
        for running in self._running_activations:
            if running.activation_id == named:
                answer = ActivationStop.STOPPED if running.stop() else ActivationStop.ALREADY_ENDED
                return self._checked(answer, "stop_activation")
        episode = await self.episode_memory.get(f"activation:{named}")
        return self._checked(
            ActivationStop.NO_SUCH_ACTIVATION if episode is None else ActivationStop.ALREADY_ENDED,
            "stop_activation",
        )

    # --- the inspection surface -------------------------------------------

    async def episodes(
        self,
        *,
        channel: ChannelIdentity | None = None,
        status: ProcessingStatus | None = None,
        cursor: NonBlankEncodableText | None = None,
        limit: int = 50,
    ) -> EpisodePage:
        """Read live episode summaries in descending capture order (ADR-0275)."""
        selected_channel, selected_status, _ = check_list(channel, status, cursor, limit)
        check_arguments(
            "episodes",
            max_bytes=self._max_payload_bytes,
            channel=selected_channel,
            status=selected_status,
            cursor=cursor,
            limit=limit,
        )
        self.calls.append(
            (
                "episodes",
                {
                    "channel": selected_channel,
                    "status": selected_status,
                    "cursor": cursor,
                    "limit": limit,
                },
            )
        )
        page = await self.episode_memory.episodes(
            channel=selected_channel, status=selected_status, cursor=cursor, limit=limit
        )
        return fit_page(
            page,
            channel=selected_channel,
            status=selected_status,
            max_bytes=self._max_payload_bytes,
        )

    async def episode_chunk(
        self,
        episode_id: EncodableText,
        *,
        version: NonBlankEncodableText | None = None,
        offset: int = 0,
        max_bytes: int = 65536,
    ) -> EpisodeChunk | None:
        """Read canonical episode bytes, preserving the exact address (ADR-0275)."""
        check_detail(episode_id, version, offset, max_bytes)
        arguments = {"episode_id": episode_id, "offset": offset, "max_bytes": max_bytes}
        if version is not None:
            arguments["version"] = version
        check_payload(
            arguments,
            max_bytes=self._max_payload_bytes,
            subject="the arguments to episode_chunk()",
        )
        self.calls.append(
            (
                "episode_chunk",
                {
                    "episode_id": episode_id,
                    "version": version,
                    "offset": offset,
                    "max_bytes": max_bytes,
                },
            )
        )
        chunk = await self.episode_memory.episode_chunk(
            episode_id, version=version, offset=offset, max_bytes=max_bytes
        )
        return fit_chunk(chunk, max_bytes=self._max_payload_bytes)

    # --- stories (ADR-0289 §4) ---------------------------------------------
    #
    # The same nine methods the engine carries, over :attr:`story_store` and with the
    # activation checks read from :attr:`episode_memory`. The logic is the engine's own
    # (`orchestration/stories.py`), named rather than copied, so the fake cannot
    # certify a consumer against a hub that answers one of these calls differently.

    async def create_story(self, members: Sequence[StoryMember]) -> StoryOutcome:
        """Create a story holding ``members``, as the owner (ADR-0289 §§3-4)."""
        named = story_members(members)
        check_arguments("create_story", max_bytes=self._max_payload_bytes, members=named)
        self.calls.append(("create_story", {"members": named}))
        if refusal := await unknown_activation(self.episode_memory, named):
            return self._checked(StoryOutcome(refusal=refusal), "create_story")
        outcome = await self.story_store.create(named, actor=StoryActor.OWNER)
        return self._checked(outcome, "create_story")

    async def link_story(
        self, story_id: Identifier, members: Sequence[StoryMember]
    ) -> StoryOutcome:
        """Add ``members`` to a story, as the owner (ADR-0289 §§3-4)."""
        target = identifier(story_id, name="story_id")
        named = story_members(members)
        check_arguments(
            "link_story", max_bytes=self._max_payload_bytes, story_id=target, members=named
        )
        self.calls.append(("link_story", {"story_id": target, "members": named}))
        if named and (refusal := await unknown_activation(self.episode_memory, named)):
            return self._checked(StoryOutcome(refusal=refusal), "link_story")
        outcome = await self.story_store.link(target, named, actor=StoryActor.OWNER)
        return self._checked(outcome, "link_story")

    async def unlink_story(
        self, story_id: Identifier, members: Sequence[StoryMember]
    ) -> StoryOutcome:
        """Remove ``members`` from a story, as the owner (ADR-0289 §§3-4)."""
        target = identifier(story_id, name="story_id")
        named = story_members(members)
        check_arguments(
            "unlink_story", max_bytes=self._max_payload_bytes, story_id=target, members=named
        )
        self.calls.append(("unlink_story", {"story_id": target, "members": named}))
        outcome = await self.story_store.unlink(target, named, actor=StoryActor.OWNER)
        return self._checked(outcome, "unlink_story")

    async def merge_stories(self, story_id: Identifier, into: Identifier) -> StoryOutcome:
        """Merge story ``story_id`` into story ``into``, as the owner (ADR-0289 §§3-4)."""
        absorbed = identifier(story_id, name="story_id")
        target = identifier(into, name="into")
        check_arguments(
            "merge_stories", max_bytes=self._max_payload_bytes, story_id=absorbed, into=target
        )
        self.calls.append(("merge_stories", {"story_id": absorbed, "into": target}))
        outcome = await self.story_store.merge(absorbed, target, actor=StoryActor.OWNER)
        return self._checked(outcome, "merge_stories")

    async def split_story(
        self,
        story_id: Identifier,
        members: Sequence[StoryMember],
        *,
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Split ``members`` off a story into a new one, with the notes named (ADR-0303 §10:1)."""
        source = identifier(story_id, name="story_id")
        named = story_members(members)
        going = story_note_ids(notes)
        check_arguments(
            "split_story",
            max_bytes=self._max_payload_bytes,
            story_id=source,
            members=named,
            notes=going,
        )
        self.calls.append(("split_story", {"story_id": source, "members": named, "notes": going}))
        outcome = await self.story_store.split(source, named, actor=StoryActor.OWNER, notes=going)
        return self._checked(outcome, "split_story")

    async def story(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryView | None:
        """Read a page of a story's members, resolved (ADR-0289 §4)."""
        target = identifier(story_id, name="story_id")
        check_story_page(cursor, limit)
        check_arguments(
            "story", max_bytes=self._max_payload_bytes, story_id=target, cursor=cursor, limit=limit
        )
        self.calls.append(("story", {"story_id": target, "cursor": cursor, "limit": limit}))

        async def read(size: int) -> StoryView | None:
            return await resolved_view(
                self.story_store, self.episode_memory, target, cursor=cursor, limit=size
            )

        return await fitted(
            read, limit, max_bytes=self._max_payload_bytes, subject="the result of story()"
        )

    async def story_log(
        self,
        story_id: Identifier,
        *,
        cursor: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> StoryLogPage | None:
        """Read a page of a story's change log, oldest first (ADR-0289 §4)."""
        target = identifier(story_id, name="story_id")
        check_story_page(cursor, limit)
        check_arguments(
            "story_log",
            max_bytes=self._max_payload_bytes,
            story_id=target,
            cursor=cursor,
            limit=limit,
        )
        self.calls.append(("story_log", {"story_id": target, "cursor": cursor, "limit": limit}))

        async def read(size: int) -> StoryLogPage | None:
            return await self.story_store.log(target, cursor=cursor, limit=size)

        return await fitted(
            read, limit, max_bytes=self._max_payload_bytes, subject="the result of story_log()"
        )

    async def stories(
        self, *, cursor: int | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> StoryPage:
        """Read a page of every story, newest first (ADR-0289 §4)."""
        check_story_page(cursor, limit)
        check_arguments("stories", max_bytes=self._max_payload_bytes, cursor=cursor, limit=limit)
        self.calls.append(("stories", {"cursor": cursor, "limit": limit}))

        async def read(size: int) -> StoryPage:
            return await self.story_store.stories(cursor=cursor, limit=size)

        page = await fitted(
            read, limit, max_bytes=self._max_payload_bytes, subject="the result of stories()"
        )
        if page is None:  # pragma: no cover — the listing always answers a page
            msg = "the story listing answered no page"
            raise StoryStoreError(msg)
        return page

    async def activation_stories(self, activation_id: Identifier) -> tuple[StoryHeader, ...]:
        """Read the stories an activation belongs to directly, newest first (ADR-0289 §4)."""
        named = identifier(activation_id, name="activation_id")
        check_arguments(
            "activation_stories", max_bytes=self._max_payload_bytes, activation_id=named
        )
        self.calls.append(("activation_stories", {"activation_id": named}))
        member = StoryMember(kind=StoryMemberKind.ACTIVATION, id=named)
        return self._checked(await self.story_store.stories_of(member), "activation_stories")

    # --- the story commands (ADR-0300 §8) -----------------------------------
    #
    # The engine's four, over the same store and the same shared logic: the summary read
    # of `orchestration/stories.py` and the standing of
    # `orchestration/story_standing.py`, each for the owner as reader.

    async def story_summary(self, story_id: Identifier) -> StorySummaryView | None:
        """Read a story's summary as the owner is shown it (ADR-0300 §8:3, §11)."""
        target = identifier(story_id, name="story_id")
        check_arguments("story_summary", max_bytes=self._max_payload_bytes, story_id=target)
        self.calls.append(("story_summary", {"story_id": target}))
        summary = await owner_summary(self.story_store, target)
        return self._checked(summary, "story_summary")

    async def story_standing(self, story_id: Identifier) -> StoryStanding | None:
        """Read where a story's matter stands, worked out for the owner (ADR-0300 §8:1)."""
        target = identifier(story_id, name="story_id")
        check_arguments("story_standing", max_bytes=self._max_payload_bytes, story_id=target)
        self.calls.append(("story_standing", {"story_id": target}))
        standing = await standing_of(
            self.story_store, self.episode_memory, target, reader=OWNER_READER
        )
        return self._checked(standing, "story_standing")

    async def add_story_note(self, story_id: Identifier, text: str) -> StoryNoteOutcome:
        """Add a note to a story, written by the owner (ADR-0300 §8:3)."""
        target = identifier(story_id, name="story_id")
        written = story_note_text(text)
        check_arguments(
            "add_story_note", max_bytes=self._max_payload_bytes, story_id=target, text=written
        )
        self.calls.append(("add_story_note", {"story_id": target, "text": written}))
        outcome = await self.story_store.append_note(target, written, author=StoryNoteAuthor.OWNER)
        return self._checked(outcome, "add_story_note")

    async def move_story_members(
        self,
        story_id: Identifier,
        to: Identifier,
        members: Sequence[StoryMember] = (),
        *,
        notes: Sequence[StoryNoteId] = (),
    ) -> StoryOutcome:
        """Move activation members, notes, or both, between stories (ADR-0304 §9)."""
        source = identifier(story_id, name="story_id")
        target = identifier(to, name="to")
        named = story_move_members(source, target, members)
        going = story_note_ids(notes)
        check_arguments(
            "move_story_members",
            max_bytes=self._max_payload_bytes,
            story_id=source,
            to=target,
            members=named,
            notes=going,
        )
        self.calls.append(
            (
                "move_story_members",
                {"story_id": source, "to": target, "members": named, "notes": going},
            )
        )
        outcome = await self.story_store.move(
            source, target, named, actor=StoryActor.OWNER, notes=going
        )
        return self._checked(outcome, "move_story_members")

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """List what is held, as summaries that carry no supports.

        Memories alone where ``kinds`` is ``None``, and an episode only where a caller
        names the episodic kind (ADR-0328 §11:2, ADR-0074 §6).
        """
        # Materialised before the first await, so a caller that mutates the sequence
        # it passed cannot change which page it gets (ADR-0085 §3d). This engine
        # never suspends, which is one of the three ways ADR-0065 permits the clause
        # to be discharged; snapshotting anyway is what makes the property a
        # property of the code rather than of the fact that it happens not to await.
        selected_bands = None if bands is None else tuple(bands)
        selected_kinds = None if kinds is None else tuple(kinds)
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "beliefs",
            max_bytes=self._max_payload_bytes,
            bands=selected_bands,
            kinds=selected_kinds,
            limit=limit,
            offset=offset,
        )
        self.calls.append(("beliefs", {"bands": selected_bands, "kinds": selected_kinds}))
        wanted = (
            frozenset({MemoryKind.MEMORY.value})
            if selected_kinds is None
            else frozenset(str(kind) for kind in selected_kinds)
        )
        matching = [
            _summary_of(belief)
            for belief in self.beliefs_held.values()
            if (selected_bands is None or belief.band in selected_bands) and belief.kind in wanted
        ]
        return self._checked(tuple(matching[offset : offset + limit]), "beliefs")

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Read one memory with its supports, or an episode, or ``None`` where none is held."""
        named = identifier(record_id, name="record_id")
        check_arguments("belief", max_bytes=self._max_payload_bytes, record_id=named)
        self.calls.append(("belief", {"record_id": named}))
        return self._checked(self.beliefs_held.get(named), "belief")

    async def forget(self, record_id: Identifier) -> bool:
        """Destroy the named belief or inspected episode."""
        named = identifier(record_id, name="record_id")
        check_arguments("forget", max_bytes=self._max_payload_bytes, record_id=named)
        self.calls.append(("forget", {"record_id": named}))
        try:  # a record that cannot be read is still destroyed, as the engine does
            conversation = episode_conversation(await self.episode_memory.get(named))
        except MemoryStoreError:
            conversation = None
        removed_episode = await self.episode_memory.delete(named)
        if conversation is not None:  # its state is sent again, as the engine counts it
            self._count_change(conversation)
        # The placement goes with the record: `forget` destroys rather than retires,
        # so leaving the entry would let a later belief minted at a recycled id
        # inherit a placement nobody set on it.
        self.placements.pop(named, None)
        removed_belief = self.beliefs_held.pop(named, None) is not None
        return self._checked(removed_episode or removed_belief, "forget")

    async def pending_candidates(self) -> tuple[PendingCandidate, ...]:
        """The pending candidates of :attr:`episode_memory`'s episodes (ADR-0329 §18:2).

        The engine's own reading, over :attr:`episode_memory` and :attr:`plan_store`
        (:func:`~ai_assistant.orchestration.candidates.held_candidates`), so the suite
        compares two implementations of the surface rather than two of the join.
        """
        self.calls.append(("pending_candidates", {}))
        held = await held_candidates(self.episode_memory, self.plan_store)
        return self._checked(held, "pending_candidates")

    # --- the hub page's approvals panel (ADR-0361 §4:6-§4:9, §8:4) --------
    #
    # The engine's own reading and tap (``orchestration.engine``'s module-level panel
    # functions), over :attr:`plan_store` and the episodes of :attr:`episode_memory`, so
    # the suite compares two implementations of the surface rather than two of the card.
    # The fake runs no activation, so every card's facts are read from an episode.

    async def approvals(self, *, limit: int = DEFAULT_PAGE_SIZE) -> ApprovalPanel:
        """The owner's requests, as the panel shows them (ADR-0361 §4:6)."""
        page_argument(limit, name="limit")
        check_arguments("approvals", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("approvals", {"limit": limit}))
        panel = await approval_panel(
            self.plan_store,
            self._approval_facts,
            person=OWNER_PERSON_ID,
            now=self.approval_clock(),
            limit=limit,
        )
        return self._checked(panel, "approvals")

    async def tap_approval(
        self, request_id: Identifier, /, *, choice: ApprovalChoice
    ) -> ApprovalPanelTap:
        """The panel's tap, as the hub page's giver (ADR-0361 §4:7-§4:9)."""
        named = identifier(request_id, name="request_id")
        chosen = approval_choice(choice)
        check_arguments(
            "tap_approval", max_bytes=self._max_payload_bytes, request_id=named, choice=chosen
        )
        self.calls.append(("tap_approval", {"request_id": named, "choice": chosen}))
        tapped, landed = await tap_on_approval_panel(
            self.plan_store,
            self._approval_facts,
            named,
            chosen,
            person=OWNER_PERSON_ID,
            now=self.approval_clock(),
        )
        if landed:
            self.approvals_woken += 1
        return self._checked(tapped, "tap_approval")

    async def _approval_facts(self, requests: Sequence[ApprovalRequest]) -> dict[str, CardFacts]:
        return await episode_card_facts(self.episode_memory, requests)

    # --- the person model, for the panels (ADR-0338 §8:1-§8:3) ------------
    #
    # The engine's own reading and writes (:mod:`~ai_assistant.orchestration.person_panel`),
    # over :attr:`person_blocks`, so the suite compares two implementations of the
    # surface rather than two of the slot. Arguments are validated first, then a fake
    # with no assembly refuses as a hub with the switch off does.

    async def person_model(
        self,
        person_id: NonBlankEncodableText,
        *,
        lists: Sequence[PersonModelList] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> PersonModelView | None:
        """One person's model, as the About you panel shows it (ADR-0338 §8:1)."""
        named = non_blank_text(person_id, name="person_id")
        selected = person_model_lists(lists)
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "person_model",
            max_bytes=self._max_payload_bytes,
            person_id=named,
            lists=selected,
            limit=limit,
            offset=offset,
        )
        self.calls.append(
            (
                "person_model",
                {"person_id": named, "lists": selected, "limit": limit, "offset": offset},
            )
        )
        blocks = person_panel.wired(self.person_blocks)
        view = await person_panel.person_model_view(
            blocks,
            named,
            limit=limit,
            offset=offset,
            lists=None if selected is None else frozenset(selected),
        )
        return self._checked(view, "person_model")

    async def profile_changes(
        self,
        person_id: NonBlankEncodableText,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[ProfileChange, ...]:
        """One page of a person's change log, the most recent first (ADR-0338 §3:5)."""
        named = non_blank_text(person_id, name="person_id")
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "profile_changes",
            max_bytes=self._max_payload_bytes,
            person_id=named,
            limit=limit,
            offset=offset,
        )
        self.calls.append(
            ("profile_changes", {"person_id": named, "limit": limit, "offset": offset})
        )
        blocks = person_panel.wired(self.person_blocks)
        page = await person_panel.profile_changes(blocks, named, limit=limit, offset=offset)
        return self._checked(page, "profile_changes")

    async def set_profile_field(
        self,
        person_id: NonBlankEncodableText,
        *,
        field: ProfileField,
        value: EncodableText | None = None,
    ) -> PersonModelEdit:
        """Set or clear one of a person's fields, on the panel (ADR-0338 §3)."""
        named = non_blank_text(person_id, name="person_id")
        which = profile_field(field)
        held = profile_value(value)
        check_arguments(
            "set_profile_field",
            max_bytes=self._max_payload_bytes,
            person_id=named,
            field=which,
            value=held,
        )
        self.calls.append(
            ("set_profile_field", {"person_id": named, "field": which, "value": held})
        )
        blocks = person_panel.wired(self.person_blocks)
        return self._checked(
            await person_panel.set_profile_field(blocks, named, which, held), "set_profile_field"
        )

    async def pin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Pin a memory, through the one checked pin (ADR-0338 §4:2, §6:3)."""
        named, memory = self._person_ids("pin_memory", person_id, memory_id=memory_id)
        blocks = person_panel.wired(self.person_blocks)
        return self._checked(await person_panel.pin_memory(blocks, named, memory), "pin_memory")

    async def unpin_memory(
        self, person_id: NonBlankEncodableText, *, memory_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Unpin a memory, erasing nothing, through the one unpin (ADR-0338 §4:7)."""
        named, memory = self._person_ids("unpin_memory", person_id, memory_id=memory_id)
        blocks = person_panel.wired(self.person_blocks)
        return self._checked(await person_panel.unpin_memory(blocks, named, memory), "unpin_memory")

    async def remove_style_mark(
        self, person_id: NonBlankEncodableText, *, mark_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Remove a style mark (ADR-0338 §5:3)."""
        named, mark = self._person_ids("remove_style_mark", person_id, mark_id=mark_id)
        blocks = person_panel.wired(self.person_blocks)
        return self._checked(
            await person_panel.remove_style_mark(blocks, named, mark), "remove_style_mark"
        )

    async def accept_person_suggestion(
        self, person_id: NonBlankEncodableText, *, suggestion_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Accept a pending suggestion (ADR-0338 §8:8, §9:2, §9:5)."""
        named, suggestion = self._person_ids(
            "accept_person_suggestion", person_id, suggestion_id=suggestion_id
        )
        blocks = person_panel.wired(self.person_blocks)
        return self._checked(
            await person_panel.accept_suggestion(blocks, named, suggestion),
            "accept_person_suggestion",
        )

    async def dismiss_person_suggestion(
        self, person_id: NonBlankEncodableText, *, suggestion_id: NonBlankEncodableText
    ) -> PersonModelEdit:
        """Dismiss a pending suggestion (ADR-0338 §9:2, §12)."""
        named, suggestion = self._person_ids(
            "dismiss_person_suggestion", person_id, suggestion_id=suggestion_id
        )
        blocks = person_panel.wired(self.person_blocks)
        return self._checked(
            await person_panel.dismiss_suggestion(blocks, named, suggestion),
            "dismiss_person_suggestion",
        )

    def _person_ids(self, method: str, person_id: str, **record: str) -> tuple[str, str]:
        """A person-model write's two ids, validated verbatim, measured and recorded."""
        named = non_blank_text(person_id, name="person_id")
        ((name, value),) = record.items()
        other = non_blank_text(value, name=name)
        check_arguments(method, max_bytes=self._max_payload_bytes, person_id=named, **{name: other})
        self.calls.append((method, {"person_id": named, name: other}))
        return named, other

    # --- the owner's placement acts (ADR-0217 §7) --------------------------

    async def guard(self, record_id: Identifier) -> Placement | None:
        """Keep one belief for the owner alone, or report that nothing is held."""
        return await self._place("guard", record_id, PlacementReach.OWNER)

    async def unguard(self, record_id: Identifier) -> Placement | None:
        """Let one belief be spoken to anyone again, or report that nothing is held."""
        return await self._place("unguard", record_id, PlacementReach.ANYONE)

    async def _place(
        self, method: str, record_id: Identifier, reach: PlacementReach
    ) -> Placement | None:
        """ADR-0217 §3's precedence over the placement this engine holds.

        The same two refusals the real engine makes, and for the same reasons: a
        ``DERIVED`` setter is not lifted by an act in either direction (§3's closing
        clause and its total order), and an act that would change neither the reach
        nor the setter writes nothing — which is what makes both operations
        idempotent in the strict sense that the second call returns exactly the
        first's value, the instant included.

        **There is no conditional write here and none is owed.** ADR-0219 §2's mode
        closes a window between two writers on one store; this engine is a dict and
        has one. What the fake owes is the *decision*, which is what every consumer
        of this surface tests against, and the interleaving arm ADR-0217 §10 pins is
        taken over a store's conditional write rather than over a fake that cannot
        have the window.
        """
        named = identifier(record_id, name="record_id")
        check_arguments(method, max_bytes=self._max_payload_bytes, record_id=named)
        self.calls.append((method, {"record_id": named}))
        if named not in self.beliefs_held:
            return self._checked(None, method)
        standing = self.placements.get(named, Placement())
        if standing.set_by is PlacementSetter.DERIVED:
            return self._checked(standing, method)
        if standing.reach is reach and standing.set_by is PlacementSetter.OWNER_ACT:
            return self._checked(standing, method)
        acted = Placement(
            reach=reach, set_by=PlacementSetter.OWNER_ACT, set_at=self.placement_clock()
        )
        self.placements[named] = acted
        return self._checked(acted, method)

    # --- the notification surface (ADR-0130 §7, §9) -----------------------
    # Backed by the canonical :class:`FakeNotificationStore` and
    # :class:`FakeNotificationPolicy` rather than by a dict of its own, so a
    # consumer testing against this engine meets the *contract's* behaviour —
    # the cap counting actionable records, a dismissal freeing a slot, an
    # expired record still enumerable — instead of whatever a second stand-in
    # happened to do. Seed it through :attr:`notification_store`.

    async def notifications(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[HeldNotification, ...]:
        """List the notifications being held, oldest first."""
        self._check_page("notifications", limit=limit, offset=offset)
        held = await self.notification_store.held(limit=limit, offset=offset)
        return self._checked(tuple(held), "notifications")

    async def dismiss_notification(self, notification_id: Identifier) -> bool:
        """Dispose of one notification without destroying it."""
        named = identifier(notification_id, name="notification_id")
        check_arguments(
            "dismiss_notification",
            max_bytes=self._max_payload_bytes,
            notification_id=named,
        )
        self.calls.append(("dismiss_notification", {"notification_id": named}))
        # **The withdrawal goes first and performs the dismissal** (ADR-0131 §3,
        # §3a). A fake that updated only the record store would still deliver what
        # it had dismissed on the next poll — certifying a consumer against a
        # contract the shipped engine does not have, which is the one thing a
        # canonical fake may not do.
        dismissed = await self.notification_outbox.withdraw(named) or (
            await self.notification_store.dismiss(named)
        )
        return self._checked(dismissed, "dismiss_notification")

    async def next_notification(
        self,
        *,
        acknowledging: Identifier | None = None,
        plays: tuple[SpokenAudioFormat, ...] = (),
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Answer ADR-0131 §1's long poll from the fake outbox, rendering as asked.

        **It does not sleep, and that is deliberate.** A fake that waited out a
        five-minute budget would make every client's delivery test slow or flaky;
        what a caller needs held is the *contract* — validate before any effect,
        acknowledge, then select — so this takes one pass and answers ``None``
        where nothing is available. A test that wants the waiting drives
        :attr:`notification_outbox` directly.

        **The rendering is ADR-0206's, applied here rather than approximated**, so a
        consumer testing against this double meets the contract's four states and not
        a subset of them. An empty ``plays`` asks for nothing and gets
        ``NOT_REQUESTED``; a candidate ADR-0206 §3 does not place gets ``WITHHELD``
        with no rendering attempted; an empty intersection of ``plays`` with
        :attr:`spoken_formats` gets ``DEGRADED``; and anything else gets
        ``RENDERED``, whose octets are a hash of the **summary** — deterministic,
        opaque, and not to be decoded by anything. The placement predicate is
        :func:`~ai_assistant.orchestration.disclosure.notification_is_speakable`
        itself, imported and never re-declared: a copy of §3's triple here would be
        exactly the drift golden rule 1 exists to prevent, arriving through the
        package whose job is to make the contract testable.

        **No rendering is retained** (ADR-0206 §1). Nothing here writes one to
        :attr:`notification_outbox`, to :attr:`notification_store` or to
        :attr:`calls`, and a redelivery of the same entry renders afresh because the
        rendering is computed from the summary on each pass.

        Args:
            acknowledging: The ``delivery_id`` being confirmed, or ``None``.
            plays: What the caller can render, in preference order. Empty asks for
                no rendering.
            budget: How long the hub may hold the request. Never waited out here.

        Returns:
            The delivery, or ``None`` where nothing is available.

        Raises:
            ValueError: If ``acknowledging`` is blank, or ``plays`` names something
                that is not a
                :class:`~ai_assistant.core.types.SpokenAudioFormat` — refused
                before the acknowledgement is applied, as ADR-0206 §7 requires.
            NotificationBudgetError: If ``budget`` is outside ADR-0131 §4's range.
        """
        named = None if acknowledging is None else identifier(acknowledging, name="acknowledging")
        # ADR-0131 §4's ordering: a refused request retires nothing, leases nothing
        # and mints nothing, so the budget is judged before the acknowledgement is
        # applied. A fake that acknowledged first would certify a client against a
        # hub that does not exist. ADR-0206 §7 puts `plays` under the same rule.
        if budget < timedelta(0) or budget > self.max_notification_budget:
            msg = (
                f"budget must be between 0 and {self.max_notification_budget} inclusive, "
                f"got {budget} (ADR-0131 §4)"
            )
            raise NotificationBudgetError(msg)
        # Coerced rather than required, for the engine's reason: over the wire
        # ADR-0087 §7's decode-validate order turns a member's value into the member
        # before the hub sees it, so a caller spelling one is conforming and this
        # double must not be stricter than the client it stands in for (ADR-0084 §4).
        # ``TypeError`` beside ``ValueError`` for the concrete engine's reason: an
        # *unhashable* member makes the enumeration's own lookup raise before any
        # value comparison happens, and that is a malformed argument like any other.
        # Letting it escape would answer a malformed `plays` with an undeclared class
        # here and the documented one there, which is the divergence ADR-0084 §4
        # forbids (#1762). The member is described through ``describe_untrusted`` for
        # the second half of the same promise: a value whose ``__repr__`` raises must
        # not be able to destroy the diagnosis from inside the message reporting it.
        wanted: list[SpokenAudioFormat] = []
        for member in plays:
            try:
                wanted.append(SpokenAudioFormat(member))
            # Total, for the concrete engine's reason and in its shape: ``ValueError``
            # is the ordinary failure, an unhashable member raises ``TypeError`` from
            # the lookup before it, and a member whose ``__repr__`` raises does so from
            # inside CPython's ``enum.__new__`` while it builds its own ``ValueError``,
            # so there is no ``ValueError`` to catch. Every one of them says the same
            # thing about the argument.
            except Exception:  # a value that cannot be coerced is malformed, however it failed
                readable = ", ".join(sorted(known.value for known in SpokenAudioFormat))
                msg = (
                    f"plays names the formats the caller can render, and "
                    f"{describe_untrusted(member)} is "
                    f"not one of them; this build declares {readable} (ADR-0206 §1, §7)"
                )
                raise ValueError(msg) from None
        plays = tuple(wanted)
        check_arguments(
            "next_notification",
            max_bytes=self._max_payload_bytes,
            acknowledging=named,
            plays=plays,
            budget=budget,
        )
        self.calls.append(
            ("next_notification", {"acknowledging": named, "plays": plays, "budget": budget})
        )
        if named is not None:
            await self.notification_outbox.acknowledge(named)
        delivery = await self.notification_outbox.claim()
        if delivery is None:
            return None
        return self._checked(self._spoken_delivery(delivery, plays), "next_notification")

    def _spoken_delivery(
        self, delivery: NotificationDelivery, plays: tuple[SpokenAudioFormat, ...]
    ) -> NotificationDelivery:
        """Apply ADR-0206 §3, §5 and §6 to one selected delivery.

        **All four of §6's degradation causes are reachable here**, which is what
        keeps this double substitutable for the engine it stands in for (ADR-0084
        §4). Two are: an empty intersection of ``plays`` with :attr:`spoken_formats`,
        and the whole projected delivery breaching ADR-0085 §8c. The other two are a
        ``SpeechError`` and a rendering over ADR-0200 §6's bound, neither of which
        this fake's own pseudo-audio can produce — a consumer that wants those drives
        the seam it holds rather than this double.

        **The payload case degrades and never raises.** ADR-0206 §6 measures the
        *whole projected* delivery and drops the rendering, and it has no second
        step: a delivery carrying no rendering is the value ADR-0131 §4's 256-byte
        reserve already guarantees fits. A fake that let the oversized rendered value
        reach its own result check would raise ``OversizedValueError`` where the
        engine returns a notification, certifying a consumer against a hub that does
        not exist — which is the one thing a canonical fake may not do.

        Args:
            delivery: What the fake outbox minted.
            plays: The caller's preference order.

        Returns:
            The delivery, carrying a rendering or the member naming why it carries
            none.
        """
        if not plays:
            return delivery
        if not notification_is_speakable(delivery.notification):
            return self._delivery_with(delivery, None, SpokenRendering.WITHHELD)
        chosen = next((member for member in plays if member in self.spoken_formats), None)
        if chosen is None:
            return self._delivery_with(delivery, None, SpokenRendering.DEGRADED)
        spoken = self._delivery_with(
            delivery,
            SpokenAudio(
                content=_pseudo_audio(delivery.notification.summary, chosen), media_type=chosen
            ),
            SpokenRendering.RENDERED,
        )
        try:
            check_payload(
                spoken,
                max_bytes=self._max_payload_bytes,
                subject="the result of next_notification()",
            )
        except OversizedValueError:
            return self._delivery_with(delivery, None, SpokenRendering.DEGRADED)
        return spoken

    @staticmethod
    def _delivery_with(
        delivery: NotificationDelivery,
        spoken: SpokenAudio | None,
        rendering: SpokenRendering,
    ) -> NotificationDelivery:
        """Rebuild one delivery around its rendering, through the validator.

        Constructed rather than ``model_copy``-updated, for the engine's reason:
        ADR-0206 §6's biconditional is *checked* on every value this path produces
        rather than trusted.

        Args:
            delivery: What the outbox minted.
            spoken: The rendering, or ``None``.
            rendering: Why it is there or is not.

        Returns:
            The delivery this poll answers with.
        """
        return NotificationDelivery(
            delivery_id=delivery.delivery_id,
            notification=delivery.notification,
            spoken=spoken,
            spoken_rendering=rendering,
        )

    async def forget_notification(self, notification_id: Identifier) -> bool:
        """Destroy one notification, reporting whether there was one to destroy."""
        named = identifier(notification_id, name="notification_id")
        check_arguments(
            "forget_notification",
            max_bytes=self._max_payload_bytes,
            notification_id=named,
        )
        self.calls.append(("forget_notification", {"notification_id": named}))
        # Withdraw before deleting, which ADR-0131 §3a makes a rule with no
        # exception: no lane deletes a record whose entry it has not already
        # withdrawn. Deleting first leaves an entry whose record is gone — not
        # departing, not expired, undetectably stale, and delivered.
        await self.notification_outbox.withdraw(named)
        destroyed = await self.notification_store.delete(named)
        return self._checked(destroyed, "forget_notification")

    async def notification_preferences(self) -> NotificationPreferences:
        """Read the three standing settings that tune proactive contact."""
        check_arguments("notification_preferences", max_bytes=self._max_payload_bytes)
        self.calls.append(("notification_preferences", {}))
        held = await self.notification_store.preferences()
        return self._checked(held, "notification_preferences")

    async def set_notification_preferences(
        self, preferences: NotificationPreferences
    ) -> NotificationPreferences:
        """Write the standing settings and re-arm what the change reaches."""
        check_arguments(
            "set_notification_preferences",
            max_bytes=self._max_payload_bytes,
            preferences=preferences,
        )
        self.calls.append(("set_notification_preferences", {"preferences": preferences}))
        await self.notification_store.set_preferences(preferences)
        held = await self.notification_store.preferences()
        return self._checked(held, "set_notification_preferences")

    # --- the conversation surface -----------------------------------------

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """List conversations, in the order they were started."""
        self._check_page("recent_conversations", limit=limit, offset=offset)
        # **Activity descending, with the id breaking ties** (ADR-0074 §2). The
        # sort key is never ``last_turn_at``: ordering by "has a turn landed" would
        # sink a conversation the user opened a minute ago below one they abandoned
        # last week — and a fake that returned insertion order would let a client's
        # ordering tests pass while production rendered stale conversations first.
        ordered = sorted(
            self.conversations_held.values(),
            key=lambda digest: (self.activity[digest.id], digest.id),
            reverse=True,
        )
        held = tuple(
            ConversationSummary(
                id=digest.id,
                started_at=digest.started_at,
                last_active_at=self.activity[digest.id],
                last_turn_at=digest.last_turn_at,
            )
            for digest in ordered
        )
        return self._checked(held[offset : offset + limit], "recent_conversations")

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        """Read one conversation: count and span, current state and devices."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("conversation", max_bytes=self._max_payload_bytes, conversation_id=named)
        self.calls.append(("conversation", {"conversation_id": named}))
        digest = self.conversations_held.get(named)
        if digest is not None:
            running = self._running_on(named)
            # ADR-0293 §8:2: an activation the reader started shows "working…" until the
            # message answering it is written, which is after its own run has ended; and
            # every one the reader holds, since several may run at once (ADR-0349 §8:1).
            running.extend(one for one in self._reader.running(named) if one not in running)
            # The state is read off the episodes as the engine reads it (ADR-0293 §8),
            # by the one function both use.
            devices = (
                await self.chat.conversation_devices(named)
                if named in self._in_chat
                else await self.chat.my_devices()
            )
            digest = digest.model_copy(
                update={
                    "state": await conversation_state(self.episode_memory, named, running=running),
                    "devices": devices or (),
                }
            )
        return self._checked(digest, "conversation")

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Forget the episodes on a conversation's place, and leave it (ADR-0293 §2:4)."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        self.calls.append(("forget_conversation", {"conversation_id": named}))
        # Every activation running from it now is told first, as the engine tells its
        # captures in flight (§2:6): what it would still write is not written back.
        for running in self._running_activations:
            if running.conversation_id == named:
                running.forgotten = True
        # The place is walked as the engine walks it (§2:4-§2:6), whether or not the
        # conversation stands, and so is the membership this fake keeps beside it.
        members = {
            episode
            for episode, conversation in self._episode_conversations.items()
            if conversation == named
        }
        members.update(await episodes_on_place(self.episode_memory, named))
        forgot = False
        for episode in sorted(members):
            if await self.episode_memory.delete(episode):
                forgot = True
            self._episode_conversations.pop(episode, None)
        self._count_change(named)  # its state is sent again, as the engine counts it
        digest = self.conversations_held.get(named)
        if digest is not None:
            self.conversations_held[named] = digest.model_copy(update={"recorded_turns": 0})
        return self._checked(forgot, "forget_conversation")

    # --- the chat space: acts in the medium and its reads (ADR-0293 §11) ---

    def _ended(self, activation: FakeActivation) -> None:
        """Stop counting ``activation`` as running (ADR-0293 §8:2)."""
        self._running_activations[:] = [
            one for one in self._running_activations if one is not activation
        ]
        if (ended := activation.conversation_id) is not None:
            self._count_change(ended)

    def _count_change(self, conversation_id: str) -> None:
        """Move the count the change stream reads a conversation's state changes by."""
        self._activation_turns[conversation_id] = self._activation_turns.get(conversation_id, 0) + 1

    def _activity(self) -> dict[str, Activity]:
        """What this fake runs, per conversation, as the engine reads its own (§8:2).

        Each running activation by its id, and every activation the chat's reader has
        an input in for, beside a count that moves at each end and at each of the
        reader's admissions and replies — the account the change stream pushes the
        current state from (ADR-0296 §4:9).
        """
        running: dict[str, list[str | None]] = {}
        for one in self._running_activations:
            if one.conversation_id is not None:
                running.setdefault(one.conversation_id, []).append(one.activation_id)
        reader = self._reader.activity()
        # ADR-0349 §8:1: several activations may run from one conversation.
        for conversation_id in reader:
            if not (reading := self._reader.running(conversation_id)):
                continue
            held = running.setdefault(conversation_id, [])
            held.extend(one for one in reading if one not in held)
        named = running.keys() | self._activation_turns.keys() | reader.keys()
        return {
            conversation_id: Activity(
                turns=self._activation_turns.get(conversation_id, 0)
                + reader.get(conversation_id, (0, None))[0],
                running=tuple(running.get(conversation_id, ())),
            )
            for conversation_id in named
        }

    def _running_on(self, conversation_id: str) -> list[str | None]:
        """The running activations started from ``conversation_id``, oldest first."""
        return [
            one.activation_id
            for one in self._running_activations
            if one.conversation_id == conversation_id
        ]

    def _joining_id(self) -> str:
        """The id the chat space mints next: the conversation joining it."""
        if not self._joining:
            msg = "the fake's chat space mints only for a conversation joining it"
            raise AssertionError(msg)
        return self._joining.pop()

    async def _joined(self, conversation_id: str) -> None:
        """Bring a held conversation into the chat space, once (ADR-0293 §2:1).

        A conversation this engine does not hold is left alone, so the store answers
        for it — refused, ``None`` or ``False`` — exactly as for a deleted one.
        """
        async with self._joining_lock:
            # Checked inside the lock: two first reads of one held conversation would
            # otherwise both start it, and the second would collide (#2696 round 1).
            if conversation_id in self._in_chat or conversation_id not in self.conversations_held:
                return
            self._joining.append(conversation_id)
            await self.chat.start()
            self._in_chat.add(conversation_id)

    async def start_conversation(self) -> ConversationSummary:
        """Start an empty conversation, shown on "my devices" (ADR-0293 §2:1)."""
        self.calls.append(("start_conversation", {}))
        candidate = f"c-{next(self._conversation_ids)}"
        while candidate in self._used_conversation_ids:
            candidate = f"c-{next(self._conversation_ids)}"
        held = self.hold_conversation(candidate)
        await self._joined(held)
        digest = self.conversations_held[held]
        return self._checked(
            ConversationSummary(
                id=held,
                started_at=digest.started_at,
                last_active_at=self.activity[held],
                last_turn_at=None,
            ),
            "start_conversation",
        )

    async def my_devices(self) -> tuple[ChatDevice, ...]:
        """Read "my devices" (ADR-0293 §3:1)."""
        self.calls.append(("my_devices", {}))
        return self._checked(await self.chat.my_devices(), "my_devices")

    async def set_my_devices(self, devices: Sequence[ChatDevice]) -> bool:
        """Replace "my devices" (ADR-0293 §3:1)."""
        held = checked_chat_devices(devices)
        check_arguments("set_my_devices", max_bytes=self._max_payload_bytes, devices=held)
        check_devices_fit(held, conversation_id=None, max_bytes=self._max_payload_bytes)
        self.calls.append(("set_my_devices", {"devices": held}))
        return self._checked(await self.chat.set_my_devices(held), "set_my_devices")

    async def set_conversation_devices(
        self, conversation_id: Identifier, *, devices: Sequence[ChatDevice]
    ) -> bool:
        """Choose one conversation's devices (ADR-0293 §3:3)."""
        named = identifier(conversation_id, name="conversation_id")
        held = checked_chat_devices(devices)
        check_arguments(
            "set_conversation_devices",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
            devices=held,
        )
        check_devices_fit(held, conversation_id=named, max_bytes=self._max_payload_bytes)
        self.calls.append(("set_conversation_devices", {"conversation_id": named, "devices": held}))
        await self._joined(named)
        changed = await self.chat.set_conversation_devices(named, held)
        return self._checked(changed, "set_conversation_devices")

    async def write_message(
        self, conversation_id: Identifier, *, message: UserMessage
    ) -> MessageReceipt:
        """Write the user's message, and answer *received* (ADR-0293 §4)."""
        named = identifier(conversation_id, name="conversation_id")
        sent = user_message(message)
        check_arguments(
            "write_message", max_bytes=self._max_payload_bytes, conversation_id=named, message=sent
        )
        check_message_fits(named, sent, max_bytes=self._max_payload_bytes)
        self.calls.append(("write_message", {"conversation_id": named, "message": sent}))
        await self._joined(named)
        receipt = await self.chat.append_message(named, sent.as_new_message())
        # The reader is told after the record, as the engine tells it (ADR-0293 §6:1),
        # a repeat included: the message it repeats may still be waiting.
        if receipt.position is not None and self.chat_reader:
            self._reader.notice(named)
        return self._checked(receipt, "write_message")

    async def composing(self, conversation_id: Identifier) -> None:
        """Take a composing signal, which writes nothing and answers nothing (ADR-0332 §5).

        Recorded in :attr:`calls` and nowhere else. It goes to no reader yet, as the
        engine's goes to none: no start wait runs for it to extend (§5:7).
        """
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("composing", max_bytes=self._max_payload_bytes, conversation_id=named)
        self.calls.append(("composing", {"conversation_id": named}))

    def _spawn_read(self, read: Coroutine[None, None, None]) -> None:
        """Start one of the reader's reads as a task this fake holds (ADR-0293 §6)."""
        task = asyncio.get_running_loop().create_task(read)
        self._chat_reads.add(task)
        task.add_done_callback(self._chat_reads.discard)

    def _chat_activation_id(self) -> str:
        """The id a reader's input is marked taken in by, and admitted with (§6:6).

        :attr:`activation_id_factory`'s, as every other activation here; one that is
        not canonical UUID4 text is replaced by a fresh one, as the engine replaces
        it, because a message the reader marks must name the activation that took it in.
        """
        try:
            minted = self.activation_id_factory()
            parsed = UUID(minted)
        except Exception:
            return str(uuid4())
        if parsed.version == 4 and str(parsed) == minted:  # noqa: PLR2004 — UUID version from ADR-0275
            return minted
        return str(uuid4())

    async def _read_in(self, taken: ChatInput) -> bool:
        """Admit one activation for the reader's input, which writes what it says.

        The input is admitted as a typed message on the conversation's channel, with
        the id the reader minted, and is running — "working…", and reachable by a
        stop — from then on. **Its first step marks the messages taken in** (ADR-0293
        §6:8); it then runs on what it marked alone, and its episode is captured as an
        event's is. It writes its message as the phases do, while it runs, through the
        engine's own writer (ADR-0307 §3): the canned reply, or *couldn't finish* where
        the pass failed (ADR-0317 §3).

        An activation that marked nothing wrote nothing, a stopped one writes nothing
        (ADR-0295 §3:3), and a cancelled one writes nothing and passes the
        cancellation on (§9:2).

        Returns:
            Whether the activation marked anything taken in.

        Raises:
            CancelledError: If the read was cancelled.
        """
        conversation_id = taken.conversation_id
        supplied = ChannelInput(
            target=ChannelIdentity(channel_type="conversation", instance_id=conversation_id),
            payload=TextChannelPayload(text=taken.text),
        )
        activation = FakeActivation.channel(supplied, WholeTextReply(), _AT)
        activation.identify(lambda: taken.activation_id)
        self._running_activations.append(activation)
        marked: list[int] = []
        failure: BaseException | None = None
        try:
            await self._reader.take_in(taken, into=marked)
            if not marked:
                msg = "the reader's input was not taken in"
                raise RuntimeError(msg)
            # ADR-0297 §4: a stop marked while the input was being taken in starts
            # nothing after it — no understanding, no message — and the pass ends.
            if not activation.stopped:
                await self._say(activation, self._chat_message(taken.narrowed(marked), activation))
        except asyncio.CancelledError as exc:
            failure = exc
        except Exception as exc:
            failure = exc
            if marked and not activation.stopped:
                # ADR-0317 §3: what was marked is consumed, so its failure is written.
                # Never raising but for a cancellation, as the phases' own write of it:
                # the pass is already ending on its own error. A cancellation there
                # ends the pass as one does anywhere, its episode still captured.
                try:
                    with contextlib.suppress(Exception):
                        await self._say(activation, couldnt_finish())
                except asyncio.CancelledError as cancelled:
                    failure = cancelled
        try:
            report = await activation.finish(
                memory=self.episode_memory,
                conversations=self.conversations_held,
                allocate=lambda conversation: self._allocate_episode(conversation, activation),
                max_bytes=self._max_payload_bytes,
                failure=failure,
                check_output=lambda: None,
            )
        finally:
            self._ended(activation)
        self._commit_episode(activation, report)
        if isinstance(failure, asyncio.CancelledError):
            raise failure
        return bool(marked)

    def _chat_message(self, taken: ChatInput, activation: FakeActivation) -> NewMessage:
        """The message the reader's input is answered with: a canned reply naming it.

        Cut to the transcript's bound and marked cut off past it, as the phases cut
        a message they write (ADR-0293 §5:2, §6:16).
        """
        conversation_id = taken.conversation_id
        activation.resolved(conversation_id)
        if conversation_id in self.activity:
            self.activity[conversation_id] = self._tick()
        activation.understand()
        text = f"This fake engine composed no real answer to {taken.text.strip()!r}."
        return NewMessage(
            author=MessageAuthor.ASSISTANT,
            text=text[:TRANSCRIPT_MESSAGE_MAX_CHARS],
            cut_off=len(text) > TRANSCRIPT_MESSAGE_MAX_CHARS,
        )

    async def _say(self, activation: FakeActivation, message: NewMessage) -> None:
        """Write one message into the activation's conversation, as the phases write it.

        The episode's ``outcome`` is the text as the conversation holds it (ADR-0307
        §10). A message the store would not take is lost, as the phases lose it: the
        activation still took its input in, so the reader goes on to what waited.
        """
        conversation_id = activation.conversation_id
        assert conversation_id is not None  # noqa: S101 — a reader's input names its conversation
        fitted = self._chat_writer.fitted(conversation_id, message)
        try:
            receipt = await self._chat_writer.send(conversation_id, fitted)
        except ConversationStoreError:
            return
        if receipt is not None and receipt.outcome is SendOutcome.RECORDED:
            activation.said(fitted.text)

    async def delete_message(self, conversation_id: Identifier, *, position: int) -> bool:
        """Delete one message, leaving its marker (ADR-0293 §5:8)."""
        named = identifier(conversation_id, name="conversation_id")
        at = check_chat_position(position, name="position")
        check_arguments(
            "delete_message", max_bytes=self._max_payload_bytes, conversation_id=named, position=at
        )
        self.calls.append(("delete_message", {"conversation_id": named, "position": at}))
        await self._joined(named)
        return self._checked(await self.chat.delete_message(named, at), "delete_message")

    async def delete_conversation(self, conversation_id: Identifier) -> bool:
        """Delete a conversation and its transcript, forgetting nothing (ADR-0293 §2:3)."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "delete_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        self.calls.append(("delete_conversation", {"conversation_id": named}))
        return self._checked(await self._deleted(named), "delete_conversation")

    async def _deleted(self, conversation_id: str) -> bool:
        """Delete a conversation from every read, its episodes left (ADR-0293 §2:3).

        The episodes and their membership stay, so forgetting still reaches them by the
        id (§2:5).
        """
        # Under the joining lock, so a first read joining the conversation to the chat
        # space either finishes before the stamp or finds it no longer held.
        async with self._joining_lock:
            held = self.conversations_held.pop(conversation_id, None) is not None
            self.activity.pop(conversation_id, None)
            stamped = conversation_id in self._in_chat and await self.chat.stamp_deleted(
                conversation_id
            )
        return held or stamped

    async def transcript(
        self,
        conversation_id: Identifier,
        *,
        before: int | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> TranscriptPage | None:
        """Read a conversation's recent messages, or older ones (ADR-0293 §5:13)."""
        named = identifier(conversation_id, name="conversation_id")
        below = None if before is None else check_chat_position(before, name="before")
        page_argument(limit, name="limit")
        check_arguments(
            "transcript",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
            before=below,
            limit=limit,
        )
        self.calls.append(
            ("transcript", {"conversation_id": named, "before": below, "limit": limit})
        )
        await self._joined(named)
        page = await self.chat.transcript(named, before=below, limit=limit)
        return self._checked(fit_transcript(page, max_bytes=self._max_payload_bytes), "transcript")

    async def chat_changes(
        self,
        *,
        after: int,
        conversation_ids: Sequence[Identifier] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ChatChanges:
        """Read every change to the chat space after a cursor (ADR-0293 §5:11)."""
        cursor = check_chat_cursor(after, name="after")
        named = chat_conversation_ids(conversation_ids)
        page_argument(limit, name="limit")
        check_arguments(
            "chat_changes",
            max_bytes=self._max_payload_bytes,
            after=cursor,
            conversation_ids=named,
            limit=limit,
        )
        self.calls.append(
            ("chat_changes", {"after": cursor, "conversation_ids": named, "limit": limit})
        )
        page = await self.chat.changes(after=cursor, conversation_ids=named, limit=limit)
        return self._checked(fit_changes(page, max_bytes=self._max_payload_bytes), "chat_changes")

    def follow_chat(self, *, after: int) -> AsyncIterator[ChatStreamChunk | ChatStreamEnd]:
        """Follow the chat space's change stream from a cursor (ADR-0298 §7).

        The engine's own stream over this fake's chat space, as the requesting device
        sees it. Like every other act here, no role is checked: this fake grants
        every device everything.
        """
        cursor = check_chat_cursor(after, name="after")
        check_arguments("follow_chat", max_bytes=self._max_payload_bytes, after=cursor)
        self.calls.append(("follow_chat", {"after": cursor}))
        return self._change_stream.follow(current_requesting_device(), after=cursor)

    # --- durable recovery --------------------------------------------------

    async def grantable_sources(self) -> tuple[GrantableSource, ...]:
        """List the **grantable** held sources, each with its location and live grant.

        A source whose declared identity is not in canonical form (ADR-0102 §4), or
        whose configured location has no UTF-8 encoding (§6), is omitted — and the
        enumeration is **not refused** for it, so the others still answer. Both
        rules are implemented rather than assumed away, because a canonical fake is
        an implementation of this contract and the shared suite holds it to the same
        clause it holds every other implementation to.
        """
        self.calls.append(("grantable_sources", {}))
        return self._checked(
            tuple(
                GrantableSource(source=identity, location=location, live=self._live_grant(identity))
                for identity, location in self.sources_held.items()
                if _is_grantable(identity, location)
            ),
            "grantable_sources",
        )

    async def grant(
        self, source: NonBlankEncodableText, *, scope: Sequence[GrantScope]
    ) -> SourceGrant:
        """Admit the source against the held identities, then record the grant.

        **``source`` is refused blank and normalised by nothing** (ADR-0102 §2), so
        this fake refuses ``grant(" calendar ")`` against a held ``"calendar"``
        exactly as the concrete engine does. Getting that wrong here would let a
        client's tests pass over the one path the wire annotation could have
        normalised, which is the direction nobody looks.

        **``INGEST`` is refused before anything is recorded** (ADR-0294 §4), through
        the same ``grant_scope`` the concrete engine uses, so a client's tests meet
        the refusal a hub would give rather than a fake that grants it.
        """
        named = non_blank_text(source, name="source")
        uses = grant_scope(scope, name="scope")
        check_arguments("grant", max_bytes=self._max_payload_bytes, source=named, scope=uses)
        self.calls.append(("grant", {"source": named, "scope": uses}))
        if named not in self.sources_held:
            # **Names no value at all** (ADR-0102 §4). ADR-0097 §9 forbids echoing
            # "no caller-supplied string beyond what the client already sent", so a
            # mistyped value cannot reach a log; the remedy is the enumeration.
            msg = (
                "no source by that name can be granted; call grantable_sources() and "
                "choose one of the identities it returns (ADR-0097 §9)"
            )
            raise UngrantableSourceError(msg)
        if not _is_grantable(named, self.sources_held[named]):
            # **Names that reader** (ADR-0102 §4), and never its location. One error
            # *class* covers all three causes (§2a — the recourse is identical), and
            # the *message* still distinguishes them: a held reader is a declared
            # constant and therefore Tier 2 by ADR-0093 §7's construction, so naming
            # it tells an operator where to look, while a caller-supplied value that
            # named nothing may not be echoed at all.
            msg = (
                f"the {named!r} source is held but cannot be granted: its declared name "
                f"is not in canonical form, or its configured location cannot be shown "
                f"to you (ADR-0102 §4, §6)"
            )
            raise UngrantableSourceError(msg)
        if self._live_grant(named) is not None:
            # What the store's atomic one-live-grant rule raises (ADR-0097 §10), so
            # the clause ADR-0102 §12 puts in the shared suite is reachable here.
            msg = f"the {named!r} source already has a live grant (ADR-0097 §4)"
            raise InvalidGrantError(msg)
        record = SourceGrant(
            id=f"grant-{len(self.grants_recorded) + 1}",
            source=named,
            scope=uses,
            decided_at=self.grant_clock(),
        )
        self.grants_recorded.append(record)
        return self._checked(record, "grant")

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Withdraw the live grant on one source, applying **no** admission check.

        A value no held source declares is not refused for that (ADR-0102 §4): it
        finds no live grant and returns ``None``, which is what keeps a grant whose
        reader was later unconfigured revocable.
        """
        named = non_blank_text(source, name="source")
        check_arguments("revoke", max_bytes=self._max_payload_bytes, source=named)
        self.calls.append(("revoke", {"source": named}))
        live = self._live_grant(named)
        if live is None:
            return self._checked(None, "revoke")
        record = SourceGrant(
            id=f"grant-{len(self.grants_recorded) + 1}",
            source=live.source,
            scope=live.scope,
            decided_at=self.grant_clock(),
            revokes=live.id,
        )
        self.grants_recorded.append(record)
        return self._checked(record, "revoke")

    async def recent_grants(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceGrant, ...]:
        """List every recorded grant and revocation, newest first."""
        positive_page_argument(limit, name="limit")
        check_arguments("recent_grants", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_grants", {"limit": limit}))
        # **Two sorts rather than one reversed key** (``SourceGrantStore.recent``):
        # the order is ``decided_at`` *descending* with ties broken by ``id``
        # *ascending*, and ``reverse=True`` over a compound key reverses **both**
        # — which puts ``grant-2`` above ``grant-1`` at one instant, the opposite
        # of what the contract states. Python's sort is stable, so sorting by the
        # tie-break first and the primary key second composes them correctly.
        by_id = sorted(self.grants_recorded, key=lambda record: record.id)
        ordered = sorted(by_id, key=lambda record: record.decided_at, reverse=True)
        return self._checked(tuple(ordered[:limit]), "recent_grants")

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """List every grant that is live right now, whatever sources are held.

        **Answered from the recorded history and never from** :attr:`sources_held`
        (ADR-0139 §1): a grant on a source this engine no longer holds is *in* this
        set, which is the state the whole operation exists for and the one an
        implementation deriving the answer from ``grantable_sources`` would drop.

        The order is :meth:`recent_grants`' and carries no meaning (ADR-0139 §2) —
        chosen so this fake answers the same question the same way twice, which is
        a display convention rather than a contract clause a test may pin.

        Raises:
            GrantError: If any source has more than one live grant, which
                :meth:`hold_grant` is the only way in — refusing the whole call
                rather than the affected source, as the contract requires.
            OversizedValueError: If the live set does not fit the contract limit.
                Refused whole rather than truncated, which is what distinguishes
                this operation from a paged one.
        """
        self.calls.append(("standing_grants", {}))
        revoked = {record.revokes for record in self.grants_recorded if record.revokes is not None}
        live = [
            record
            for record in self.grants_recorded
            if record.revokes is None and record.id not in revoked
        ]
        seen: set[str] = set()
        for record in live:
            if record.source in seen:
                msg = (
                    f"the grant store holds more than one live grant for source "
                    f"{record.source!r}, where ADR-0097 §4 allows one; the store is corrupt"
                )
                raise GrantError(msg)
            seen.add(record.source)
        by_id = sorted(live, key=lambda record: record.id)
        ordered = sorted(by_id, key=lambda record: record.decided_at, reverse=True)
        return self._checked(tuple(ordered), "standing_grants")

    # --- the connection surface (ADR-0151 §1) ------------------------------

    async def connect_account(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account, minting a reference through :attr:`connections`.

        **The local refusals are implemented here rather than delegated**, which
        is what ADR-0085 §9 asks of *every* implementation: a fake that let an
        oversized identity or one equal to the credential through would let a
        client's tests pass over the one path where the client is the last thing
        between a user's secret and the wire (ADR-0151 §5).
        """
        secret = secret_value(credential)
        named = non_blank_text(identity, name="identity")
        # **One call, one read of the plaintext** (ADR-0151 §5, §11). §5's exact
        # comparison against the identity and §11's frame measurement need the same
        # value, and `orchestration` holds it once: a second helper would give this
        # package two plaintext-handling sites where §5 obliges one.
        check_provisioning_call(
            "connect_account",
            max_bytes=self._max_payload_bytes,
            identity=named,
            credential=secret,
        )
        self.calls.append(("connect_account", {"identity": named}))
        return self._checked(
            await self.connections.provision(identity=named, credential=secret), "connect_account"
        )

    async def reprovision_account(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under an existing reference."""
        secret = secret_value(credential)
        handle = identifier(reference, name="reference")
        named = non_blank_text(identity, name="identity")
        check_provisioning_call(
            "reprovision_account",
            max_bytes=self._max_payload_bytes,
            identity=named,
            credential=secret,
            reference=handle,
        )
        self.calls.append(("reprovision_account", {"reference": handle, "identity": named}))
        return self._checked(
            await self.connections.reprovision(handle, identity=named, credential=secret),
            "reprovision_account",
        )

    async def connect_keyless_account(self, *, identity: NonBlankEncodableText) -> ConnectedAccount:
        """Connect a source that needs no credential, through :attr:`connections`.

        The local refusals are implemented here rather than delegated, on
        :meth:`connect_account`'s reason (ADR-0085 §9, ADR-0325 §4:3).
        """
        named = non_blank_text(identity, name="identity")
        check_keyless_call(
            "connect_keyless_account", max_bytes=self._max_payload_bytes, identity=named
        )
        self.calls.append(("connect_keyless_account", {"identity": named}))
        return self._checked(
            await self.connections.provision_keyless(identity=named), "connect_keyless_account"
        )

    async def disconnect_account(self, reference: Identifier) -> ConnectedAccount | None:
        """Disconnect a reference, or report that no live record was removed."""
        handle = identifier(reference, name="reference")
        check_arguments("disconnect_account", max_bytes=self._max_payload_bytes, reference=handle)
        self.calls.append(("disconnect_account", {"reference": handle}))
        return self._checked(await self.connections.disconnect(handle), "disconnect_account")

    async def connected_accounts(self) -> tuple[ConnectedAccount, ...]:
        """Every live record, pending ones included and never truncated."""
        self.calls.append(("connected_accounts", {}))
        return self._checked(await self.connections.connected(), "connected_accounts")

    async def recent_connection_acts(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[ConnectionAct, ...]:
        """What was done, newest first, one row per ``(reference, revision)``."""
        positive_page_argument(limit, name="limit")
        check_arguments("recent_connection_acts", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_connection_acts", {"limit": limit}))
        return self._checked(
            await self.connections.recent_acts(limit=limit), "recent_connection_acts"
        )

    # --- the audit trail's two reads (ADR-0186 §1) -------------------------

    async def recent_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """What the permission layer ruled, newest first, bounded by ``limit``.

        ``limit`` is refused when it is **not strictly positive**, locally and
        before the trail is touched, on ``recent_grants``' reason (ADR-0186 §3).
        """
        positive_page_argument(limit, name="limit")
        check_arguments("recent_decisions", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_decisions", {"limit": limit}))
        return self._checked(
            _ordered_decisions(await self.trail.recent(limit=limit)), "recent_decisions"
        )

    async def export_decisions(self) -> tuple[PermissionDecision, ...]:
        """Every recorded decision, in :meth:`recent_decisions`' order.

        **Sorted here rather than relayed**, which is ADR-0186 §2's clause and the
        reason this fake holds a whole :class:`~ai_assistant.core.protocols.AuditTrail`
        rather than a list: ``AuditTrail.export`` promises no order, so a trail is
        free to hand back insertion order and the engine operation still owes §2's.
        """
        self.calls.append(("export_decisions", {}))
        return self._checked(_ordered_decisions(await self.trail.export()), "export_decisions")

    # --- the read trail's two reads (ADR-0186 §10) -------------------------

    async def recent_reads(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceReadRecord, ...]:
        """What this system read from a source, newest-recorded first.

        Relayed rather than reordered: ``SourceReadTrail.recent`` already promises
        this order (ADR-0185 §6), and these rows carry nothing an implementation
        could correctly sort by — see :meth:`export_reads`.
        """
        positive_page_argument(limit, name="limit")
        check_arguments("recent_reads", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_reads", {"limit": limit}))
        return self._checked(tuple(await self.reads.recent(limit=limit)), "recent_reads")

    async def export_reads(self) -> tuple[SourceReadRecord, ...]:
        """Every read attempt still held, in :meth:`recent_reads`' order.

        **Reversed here rather than relayed** (ADR-0186 §10): the store's ``export``
        is in *recording* order and the listing is its reverse, so an implementation
        handing the list back as it arrived would break §2's prefix property across
        this pair. Reversed and never **sorted** — a ``SourceReadRecord`` has no
        sequence number, an unordered caller-minted ``id``, and a caller-supplied
        ``checked_at`` the store itself refuses to key on (ADR-0185 §6).

        What comes back is the **horizon** rather than the history: the store prunes
        oldest-first, and no surface reports this as a complete record (ADR-0185 §9).
        """
        self.calls.append(("export_reads", {}))
        return self._checked(tuple(reversed(await self.reads.export())), "export_reads")

    # --- the trail's two invocation reads (ADR-0192 §4) --------------------

    async def recent_invocations(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecordedInvocation, ...]:
        """What the system did on an authorisation, newest first, bounded by ``limit``.

        ``limit`` is refused when it is **not strictly positive**, locally and
        before the trail is touched, on ``recent_decisions``' reason (ADR-0192 §4).
        """
        positive_page_argument(limit, name="limit")
        check_arguments("recent_invocations", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_invocations", {"limit": limit}))
        return self._checked(
            _ordered_invocations(await self.trail.recent_invocations(limit=limit)),
            "recent_invocations",
        )

    async def export_invocations(self) -> tuple[RecordedInvocation, ...]:
        """Every invocation row, in :meth:`recent_invocations`' order.

        **Sorted here rather than relayed**, on ``export_decisions``' reasoning:
        ADR-0192 §4 makes the order the *operation's* guarantee "over a list it has
        materialised", so a fake handing back whatever a trail produced would be
        conforming by luck rather than by construction.
        """
        self.calls.append(("export_invocations", {}))
        return self._checked(
            _ordered_invocations(await self.trail.export_invocations()), "export_invocations"
        )

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """Relay the ledger's two period totals, unchanged (ADR-0194 §6).

        **Relayed rather than assembled**, which is the opposite of what
        :meth:`export_invocations` above does and is right for the opposite reason:
        ADR-0194 §5 makes the order, the one-clock-read coherence and the
        period bounds the **ledger's** guarantees, so a fake computing them here
        would be a second implementation of the rule that the shared suite could
        then only compare against itself.
        """
        self.calls.append(("spend_totals", {}))
        return self._checked(await self.spend.spend_totals(), "spend_totals")

    def _live_grant(self, source: str) -> SourceGrant | None:
        """The grant on ``source`` no recorded revocation names (ADR-0097 §4).

        **Derived from the ``revokes`` relation alone**, never by comparing two
        ``decided_at`` values, which is what ADR-0102 §3's second normative clause
        exists for: a revocation timestamped *before* the grant it revokes is
        permitted, so a fake that ordered by time would report a withdrawn grant as
        live — on exactly the case the shared suite is written to reach.
        """
        revoked = {record.revokes for record in self.grants_recorded if record.revokes is not None}
        for record in self.grants_recorded:
            if record.source == source and record.revokes is None and record.id not in revoked:
                return record
        return None

    # --- setting one up ----------------------------------------------------

    def hold(  # noqa: PLR0913 — a wording, a band and the facts ADR-0328 §15 projects; each is one thing a caller decides on its own
        self,
        record_id: str,
        *,
        content: str,
        band: BeliefBand = BeliefBand.ASSERTED,
        attestation: Attestation | None = None,
        rests_on_outside_content: bool = False,
        legacy: bool = False,
        placement: Placement | None = None,
    ) -> Belief:
        """Put one memory in memory, and return its single-memory view.

        It rests on one support whose origin ranks at ``band`` (:func:`_held_support`),
        and is projected by ``core``'s own projection
        (:func:`~ai_assistant.core.types.belief_view`), so this fake represents no state
        the real projection cannot produce: its standing, whether it rests on outside
        content and whether it is legacy are computed from that support, never set.

        Args:
            record_id: The memory's id.
            content: Its wording.
            band: The band its one support's origin ranks it in.
            attestation: The source details of an ``ATTESTED`` memory's support.
            rests_on_outside_content: Whether a ``DERIVED`` memory's support is outside.
            legacy: Whether it rests on a record stored before ADR-0328 instead.
            placement: Who may receive it (ADR-0217 §1); ``None`` leaves the default.

        Returns:
            The memory now held, as the single-memory view projects it.
        """
        support = _held_support(
            band,
            attestation=attestation,
            outside=rests_on_outside_content,
            legacy=legacy,
            record_id=record_id,
        )
        memory = Memory(
            id=record_id,
            content=content,
            supports=(support,),
            operations=(
                MemoryOperation(
                    kind=MemoryOperationKind.CREATE,
                    cites=support.points_at,
                    at=_AT,
                    by=support.added_by,
                ),
            ),
        )
        held = belief_view(memory, now=_AT, contents={support.points_at: content})
        self.beliefs_held[record_id] = held
        # The placement follows the belief it belongs to, so seeding over an id this
        # engine already holds **replaces** it rather than inheriting the last one's.
        self.placements.pop(record_id, None)
        if placement is not None:
            self.placements[record_id] = placement
        return held

    def hold_episode(
        self,
        record_id: str,
        *,
        content: str,
        occurred_at: datetime = _AT,
        placement: Placement | None = None,
    ) -> Belief:
        """Put one episode in memory, and return the view ``belief`` reads it as.

        Projected by ``core``'s :func:`~ai_assistant.core.types.episode_view`, so it
        is listed only where a caller names the episodic kind (ADR-0074 §6).

        Args:
            record_id: The episode's id.
            content: Its content.
            occurred_at: When it happened.
            placement: Who may receive it; ``None`` leaves the default.

        Returns:
            The episode's view.
        """
        held = episode_view(
            EpisodicMemory(
                id=record_id,
                content=content,
                occurred_at=occurred_at,
                provenance=Provenance(
                    source=MemorySource.OBSERVED, confidence=0.9, last_updated=occurred_at
                ),
            )
        )
        self.beliefs_held[record_id] = held
        self.placements.pop(record_id, None)
        if placement is not None:
            self.placements[record_id] = placement
        return held

    def _tick(self) -> datetime:
        """The next instant on this engine's logical clock.

        Strictly increasing rather than "one tick past whatever this conversation
        last had", which would let a continued conversation land *equal* to one
        started after it and leave the ordering to the tie-break.
        """
        return _AT + _TICK * next(self._ticks)

    def hold_conversation(self, conversation_id: str) -> str:
        """Record one conversation, and return its id.

        The seeding lever, and what a turn call naming no conversation uses. The
        conversation joins the chat space (:attr:`chat`) the first time an act or a
        read of the chat space names it, given "my devices" as they then stand;
        :meth:`start_conversation`, the act in the medium, joins it at once
        (ADR-0293 §2:1).

        Its activity stamp starts one tick later than the last conversation's, so
        "most recently active first" is a fact the ordering can be tested against
        rather than an accident of a fixed clock.
        """
        # A fresh automatic channel must not reuse a deleted identity while an
        # earlier activation is still finishing its deletion verification.
        self._used_conversation_ids.add(conversation_id)
        started = self._tick()
        self.conversations_held[conversation_id] = ConversationDigest(
            id=conversation_id, started_at=started, last_turn_at=None, recorded_turns=0
        )
        self.activity[conversation_id] = started
        return conversation_id

    def hold_source(self, identity: str, *, location: str | None = None) -> None:
        r"""Make one source known to this engine, grantable or not.

        The scriptable half ADR-0102 §12 item 3 asks for, and it accepts the
        **defective** states as well as the ordinary ones, because those are
        legitimate states of a *hub* rather than test errors: a reader really can
        declare a name that is not in canonical form, and a configured path really
        can have no UTF-8 encoding (Linux pathnames are bytes and Python surfaces an
        undecodable one through ``surrogateescape``). What ADR-0102 §4 and §6 then
        require is that such a source is **neither enumerated nor granted**, and
        ADR-0102 §12 item 2 puts that clause in the *shared* conformance suite — so
        this fake has to be able to be put into the state the suite then checks.

        **An earlier draft of this fake refused those inputs instead**, on the
        argument that they are defects in a reader and a fake engine has no readers.
        That is the wrong shape twice over: a canonical fake is an *implementation*,
        so implementing a rule is its job rather than duplication to be avoided; and
        refusing here would leave the suite unable to reach the clause at all, which
        is precisely how a future engine or spoke could breach the contract and
        still come back green.

        A source held **without** a location is a third case and not a defect at
        all: §6 makes it grantable with ``location`` absent, because with nothing
        configured the disclosure obligation is vacuous.

        Args:
            identity: The declared identity, as a reader's ``name`` would return it.
                Not required to be admissible.
            location: Where the source reads from, or ``None`` where nothing is
                configured. Not required to be encodable.
        """
        self.sources_held[identity] = location

    def hold_grant(
        self,
        identity: str,
        *,
        scope: Sequence[GrantScope] = (GrantScope.NOTIFY,),
        decided_at: datetime | None = None,
        revokes: str | None = None,
    ) -> SourceGrant:
        """Append one grant or revocation directly, and return it.

        The **timestamp is settable** so a test can reach the one case ADR-0102 §3's
        second clause is about and nothing else reaches: a revocation whose
        ``decided_at`` is *earlier* than the grant it revokes, which ADR-0097 §4
        permits explicitly and which an implementation deriving liveness from a
        time-ordered page gets wrong.

        **No admission check and no one-live-grant check**, which is what makes two
        further states reachable — both of them states a real hub can be in and
        neither reachable through the surface (ADR-0139 §8). A grant on an
        ``identity`` this engine does not hold is the whole subject of
        ``standing_grants``: an operator unsets a reader's path and the grant stays
        live while disappearing from ``grantable_sources``. And **calling this
        twice for one source** seeds the corrupt store ADR-0139 §2 requires
        ``standing_grants`` to refuse — the state ``record``'s atomic check makes
        unreachable through any writer, so a suite that could not script it would
        leave an implementation returning both grants passing every case.

        Args:
            identity: The source the record is about. Not required to be held.
            scope: The uses. On a revoking record this must transcribe the revoked
                grant's scope verbatim, which is the store's own invariant.
            decided_at: When the user decided; defaults to this engine's logical
                clock.
            revokes: The id of the grant this record revokes, or ``None``.

        Returns:
            The appended record.
        """
        record = SourceGrant(
            id=f"grant-{len(self.grants_recorded) + 1}",
            source=identity,
            scope=tuple(scope),
            decided_at=decided_at if decided_at is not None else self._tick(),
            revokes=revokes,
        )
        self.grants_recorded.append(record)
        return record

    def _checked[T](self, result: T, method: str) -> T:
        """Refuse a result the contract does not admit, before returning it (§8c)."""
        check_payload(
            result, max_bytes=self._max_payload_bytes, subject=f"the result of {method}()"
        )
        return result

    def _check_page(self, method: str, *, limit: int, offset: int) -> None:
        """Refuse a malformed page argument locally, then measure the call."""
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(method, max_bytes=self._max_payload_bytes, limit=limit, offset=offset)
        self.calls.append((method, {"limit": limit, "offset": offset}))


def _event_result(target: ChannelIdentity, ended: ActivationEnding) -> ChannelResult:
    """An event's result: how its activation ended, and nothing it wrote (ADR-0313 §4:4)."""
    return ChannelResult(
        channel=target, capture=UNCAPTURED, result=InformationalEventResult(ended=ended)
    )


def _stopped_failure(
    activation: FakeActivation, failure: BaseException | None
) -> BaseException | None:
    """What a turn call awaiting ``activation`` is answered with (ADR-0297 §4).

    ``ActivationStoppedError`` in place of what a stopped pass would otherwise return
    or raise; a cancellation still propagates as itself.
    """
    if not activation.stopped or isinstance(failure, asyncio.CancelledError):
        return failure
    stopped = ActivationStoppedError("the activation was stopped before it finished (ADR-0297 §4)")
    stopped.__cause__ = failure
    return stopped


def _is_grantable(identity: str, location: str | None) -> bool:
    """Whether a held source may be enumerated and granted (ADR-0102 §4, §6).

    Canonical, non-blank, encodable identity; and a configured location that can be
    shown, where there is one. **Absent is not the same as unshowable**: nothing
    configured makes ADR-0097 §9a's disclosure obligation vacuous and leaves the
    source grantable, while a location that exists and cannot be written down fails
    closed — offering it would advertise a source no conforming client may grant.
    """
    if not identity.strip() or identity != identity.strip():
        return False
    try:
        encodable_text(identity)
        if location is not None:
            encodable_text(location)
    except ValueError:
        return False
    return True


def _ordered_decisions(rows: Sequence[PermissionDecision]) -> tuple[PermissionDecision, ...]:
    """Put ADR-0186 §2's total order on what a trail read returned.

    ``decided_at`` **descending**, ties broken by ``id`` **ascending** — the order
    ADR-0021 §4 fixes for ``AuditTrail.recent`` and ADR-0186 §2 puts on both engine
    operations, the export included, whose store contract states none.

    **Two sorts rather than one reversed key**, exactly as :meth:`recent_grants`
    does it: ``reverse=True`` over a compound key reverses **both** halves, which
    would put ``d-2`` above ``d-1`` at one instant. Python's sort is stable, so
    sorting by the tie-break first and the primary key second composes them
    correctly.
    """
    by_id = sorted(rows, key=lambda decision: decision.id)
    return tuple(sorted(by_id, key=lambda decision: decision.decided_at, reverse=True))


def _ordered_invocations(rows: Sequence[RecordedInvocation]) -> tuple[RecordedInvocation, ...]:
    """Put ADR-0192 §4's total order on what an invocation read returned.

    The row's ``recorded_at`` **descending**, ties broken by the row's ``id``
    **ascending** — :func:`_ordered_decisions`' shape, with the key one level down
    on :attr:`RecordedInvocation.invocation`, because the join adds the tool, the
    capability and the egress boolean and restates neither the instant nor the id
    (ADR-0192 §2).
    """
    by_id = sorted(rows, key=lambda row: row.invocation.id)
    return tuple(sorted(by_id, key=lambda row: row.invocation.recorded_at, reverse=True))


#: The episode a held memory's support points at: a fake one, which the fake never
#: resolves, so a held memory's support content is its own wording (``hold``).
_HELD_EPISODE = "fake:held"


def _held_support(
    band: BeliefBand,
    *,
    attestation: Attestation | None,
    outside: bool,
    legacy: bool,
    record_id: str,
) -> MemorySupport:
    """The one support a held memory rests on, its origin chosen for ``band`` (ADR-0328 §4).

    ``ASSERTED`` is the user saying it, ``ATTESTED`` an evidence item (outside, with
    ``attestation`` as its source details), and ``DERIVED`` a remember call, outside
    where ``outside`` says so; ``legacy`` a record stored before ADR-0328.
    """
    if legacy:
        return stamped_support(
            MemorySupport(
                points_at=LegacyPart(record=record_id),
                origin=SupportOrigin.LEGACY_OUTSIDE if outside else SupportOrigin.LEGACY,
                direction=SupportDirection.FOR,
                backs_as_worded=True,
                added_at=_AT,
                added_by=MemoryWriterName.MIGRATION,
                carries={"id": record_id},
            ),
            None,
        )
    match band:
        case BeliefBand.ASSERTED:
            part: SupportPart = InputPart(episode=_HELD_EPISODE)
            origin = SupportOrigin.USER_MESSAGE
        case BeliefBand.ATTESTED:
            part = EvidenceItemPart(episode=_HELD_EPISODE, digest=0, item=0)
            origin = SupportOrigin.EVIDENCE
        case BeliefBand.DERIVED:
            part = RememberCallPart(episode=_HELD_EPISODE, effect="fake-effect")
            origin = SupportOrigin.REMEMBERED_OVER_OUTSIDE if outside else SupportOrigin.REMEMBERED
        case _:  # pragma: no cover - exhaustive
            assert_never(band)
    # ADR-0345 §2:2: held as a writer would have recorded it, its holder set by §2's table.
    return stamped_support(
        MemorySupport(
            points_at=part,
            origin=origin,
            direction=SupportDirection.FOR,
            backs_as_worded=True,
            when=_AT,
            source_details=attestation,
            added_at=_AT,
            added_by=MemoryWriterName.REMEMBER,
        ),
        None,
    )


def _summary_of(belief: Belief) -> BeliefSummary:
    """The listing's summary of one held memory: its fields, its supports left out."""
    return BeliefSummary.model_validate(belief.model_dump(exclude={"supports"}))


def _pseudo_audio(text: str, media_type: SpokenAudioFormat) -> str:
    """Deterministic pseudo-audio for ``text``, as padded canonical base64.

    The octets are a hash of the answer and the container, so one answer renders
    one way and two answers render differently. **Nothing about them is audio**,
    and nothing may decode them: ADR-0200 §4 makes "the rendering says the text"
    the synthesizer's obligation, discharged in its own conformance suite, and
    forbids any consumer from inspecting a rendering to check it. What this fake
    guarantees is the property a consumer may lean on — that ``spoken`` is the
    rendering of ``outcome.reply`` and of nothing else.
    """
    return b64encode(hashlib.sha256(f"{media_type.value}\0{text}".encode()).digest()).decode(
        "ascii"
    )


__all__ = ["FakeAssistantEngine"]

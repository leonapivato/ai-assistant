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
from typing import TYPE_CHECKING, Final, assert_never
from uuid import UUID, uuid4

from ai_assistant.core.channel_validation import snapshot
from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.device_context import current_requesting_device
from ai_assistant.core.episode_encoding import check_detail, check_list
from ai_assistant.core.errors import (
    ActivationStoppedError,
    ConversationStoreError,
    GrantError,
    InvalidGrantError,
    InvalidRecipientGrantError,
    MemoryStoreError,
    ModelTimeoutError,
    NotificationBudgetError,
    OversizedValueError,
    PlanningError,
    StoryStoreError,
    UngrantableActError,
    UngrantableSourceError,
    UntrustableDestinationError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    ActionPlan,
    ActivationEnding,
    ActivationStop,
    AnswerKind,
    AnswerOutcome,
    AttemptOutcome,
    AttemptReport,
    Attestation,
    Authorization,
    AuthorizationDisposition,
    AuthorizationProjection,
    AuthorizationSettlement,
    AuthorizationView,
    Belief,
    BeliefBand,
    BeliefSummary,
    ChannelIdentity,
    ChannelInput,
    ChannelResult,
    ClarificationWithdrawal,
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    ConversationDigest,
    ConversationSummary,
    CurrentContext,
    DestinationTrust,
    DestinationTrustRecord,
    DriveWithheld,
    EgressBinding,
    EpisodeCaptureReport,
    EpisodeChunk,
    EpisodePage,
    ForecastNotRead,
    Goal,
    GoalAbandonment,
    GoalBrief,
    GoalInterpretation,
    GoalSummary,
    GrantableSource,
    GrantScope,
    Ground,
    InformationalEventResult,
    MemoryKind,
    MemorySource,
    NotificationDelivery,
    OutboundReach,
    OutboundStatement,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    ProcessingStatus,
    Provenance,
    Question,
    QuestionState,
    ReadKind,
    RecipientGrant,
    RecordedChannelTrigger,
    RecordedInvocation,
    RecordedSpeechInput,
    Retirement,
    SourceGrant,
    SpendTotal,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryState,
    SpokenRendering,
    SpokenReply,
    StepStatus,
    StoryActor,
    StoryMember,
    StoryMemberKind,
    StoryNoteAuthor,
    StoryNoteId,
    StoryOutcome,
    TextChannelPayload,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
    Warrant,
    WholeTextReply,
    chat_conversation_ids,
    check_chat_cursor,
    check_chat_position,
    check_story_page,
    checked_chat_devices,
    describe_untrusted,
    encodable_text,
    rests_on_recorded_external_content,
    secret_value,
    story_members,
    story_move_members,
    story_note_ids,
    story_note_text,
    user_message,
)
from ai_assistant.orchestration.authorization_surface import is_live, view_of
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
    chat_effects,
    chat_reply,
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
from ai_assistant.orchestration.episode_reads import fit_chunk, fit_page
from ai_assistant.orchestration.payloads import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    check_arguments,
    check_payload,
    check_provisioning_call,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
    utc_instant,
)
from ai_assistant.orchestration.recipient_grants import (
    rides_an_establishing_act,
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
from ai_assistant.testing.destination_trust import FakeDestinationTrustStore
from ai_assistant.testing.goal_authorizations import (
    AUTHORIZATION_NOW,
    FakeGoalAuthorizationStore,
)
from ai_assistant.testing.memory import FakeMemoryStore
from ai_assistant.testing.notifications import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)
from ai_assistant.testing.permissions import FakeAuditTrail
from ai_assistant.testing.reads import FakeSourceReadTrail
from ai_assistant.testing.recipient_grants import FakeRecipientGrantStore
from ai_assistant.testing.stories import FakeStoryStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Coroutine, Sequence

    from ai_assistant.core.protocols import AuditTrail, SourceReadTrail, SpendLedger
    from ai_assistant.core.types import (
        ChatChanges,
        ChatDevice,
        ChatStreamChunk,
        ChatStreamEnd,
        ConnectedAccount,
        ConnectionAct,
        DurableIdentifier,
        EncodableText,
        HeldNotification,
        Identifier,
        MessageReceipt,
        NonBlankEncodableText,
        NotificationPreferences,
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
        UtcInstant,
    )

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


#: The retention bound §4 of ADR-0198 reuses, and the ceiling the real engine
#: defaults to. Stated here rather than imported, because it is a deployment
#: default rather than a contract value — what the contract fixes is that the two
#: numbers are **one**, not what the number is.
_DEFAULT_MAX_OUTSTANDING: Final = 1024


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


#: The step statuses ADR-0262 §4's **third** ending condition admits, stated as the
#: three it names rather than as the four it excludes: *"every step of every execution
#: it names stands ``SUCCEEDED``, ``FAILED`` or ``SKIPPED`` — so none stands
#: ``PENDING``, ``AWAITING_APPROVAL``, ``RUNNING`` or ``INDETERMINATE``"*.
#:
#: **Not** :data:`~ai_assistant.core.types.TERMINAL_STEP_STATUSES`, which is a different
#: set for a different question — ``FAILED`` sits outside it *"(it may still be
#: retried)"*, and reading it here would refuse a failed step §4 admits, so the
#: attempt an implementation could never end is exactly the one §4's limb 1 reports.
_ENDING_ADMITS: Final[frozenset[StepStatus]] = frozenset(
    {StepStatus.SUCCEEDED, StepStatus.FAILED, StepStatus.SKIPPED}
)


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

    Attributes:
        turn_outcome: The turn the activation the reader runs for a written message
            ends with (ADR-0293 §6, §10). Defaults to a turn whose plan had no step —
            a real ratified shape, not a stub.
        outbound_statement: ADR-0264 §7's statement every outcome this engine
            *composes* carries, or ``None`` — the default — for a fresh
            ``NOT_REACHED`` minted per outcome. Script it to drive a rendering
            surface over ``REACHED`` and ``INDETERMINATE``.
        attempt_report: ADR-0262 §6's report every outcome this engine *composes a
            reply for* carries, or ``None`` — the default — because a fake ends no
            attempt. Script it to drive a rendering surface over each of the six
            ``AttemptOutcome`` members a fixed statement is owed for.
        forecast_not_read: ADR-0260 §10's member every outcome this engine *composes*
            carries, or ``None`` — the default — because a fake services no forecast
            read. Script it to drive a rendering surface over each of the six
            ``ForecastNotRead`` members a fixed statement is owed for.
        drive_withheld: ADR-0261 §7's member every outcome this engine *composes*
            carries, or ``None`` — the default — because a fake takes no ``→ RUNNING``
            claim and so meets no ``ClaimRefused``. Script it to drive a rendering
            surface over each of the seven ``DriveWithheld`` members a fixed statement
            is owed for.
        answered: What :meth:`answer` returns, or ``None`` to synthesise one from
            the question's own state.
    """

    def __init__(  # noqa: PLR0915 — one assignment per table this fake keeps, and each is a distinct population a `resume` presenting a handle is decided from; ADR-0244 §5 adds a fourth
        self,
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        max_outstanding_confirmations: int = _DEFAULT_MAX_OUTSTANDING,
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
            max_outstanding_confirmations: The concrete engine's confirmation
                ceiling. It bound the settled records a ``resume`` restated (ADR-0198
                §4), which left with ``resume`` (ADR-0309 §5:1), so nothing here reads
                it now. Guarded exactly as the concrete
                engine guards it, **classification included**: ADR-0084 §4's
                substitutability runs in both directions, so a fake that admitted a
                deployment no engine admits would let a consumer's tests pass over a
                configuration production cannot be built into — and a fake that
                refused the same value with a different class would make the two
                disagree about what kind of failure it is. Unrefused, the value
                surfaces later and as something else: ``1.5`` would bound the
                retention at two, and ``0`` would discard from an empty table on the
                first settlement.
            chat_reader: Whether a message written into a conversation is answered
                (ADR-0293 §6, §10), as the engine's ``chat_reader`` says the same; the
                initial value of :attr:`chat_reader`.

        Raises:
            TypeError: If ``max_outstanding_confirmations`` or ``max_payload_bytes``
                is not an **exact** ``int``. A
                ``bool`` is the named case — it is an ``int`` subclass, and a flag is
                not a count — and a ``float`` like ``1.5`` is refused rather than
                compared, which is the guard the concrete engine states in these
                words (:func:`_check_positive_int`).
            ValueError: If either is not positive.
        """
        _check_positive_int(max_outstanding_confirmations, name="max_outstanding_confirmations")
        # ADR-0085 §8c's limit, guarded on the same terms — the widest of the two,
        # since every argument check and every result check this double performs
        # measures against this one number (#1686).
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
        self.questions_open: dict[str, Question] = {}
        self.questions_interrupted: dict[str, Question] = {}
        #: Questions in a terminal state — declined, applied, stale, re-deferred.
        #: Neither enumeration shows one and :meth:`answer` refuses it, because
        #: "that question is not open" is what the surface has to say about it.
        self.questions_settled: dict[str, Question] = {}
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
        #: The delivery row of each spoken turn's episode (ADR-0205 §3). No spoken turn
        #: runs since ``converse_spoken`` retired (ADR-0313 §3:1), and the rows leave
        #: with the conversation store's delivery members (§3:3).
        self.deliveries: dict[str, SpokenDelivery] = {}
        #: Which conversation each captured episode was recorded in, by episode id.
        #: Every id is ``activation:<activation_id>``, fixed at admission
        #: (ADR-0283 §2), so membership is retained here rather than read off the id.
        self._episode_conversations: dict[str, str] = {}
        activation_ids = count(1)
        self.activation_id_factory: Callable[[], str] = lambda: str(
            UUID(int=next(activation_ids), version=4)
        )
        self._ticks = count(1)
        #: Where :meth:`answer` draws the id of the belief an accepted answer writes.
        #: A **counter rather than the store's size**, because the store shrinks: a
        #: ``forget``, or an answer that retires what it names, frees a number the size
        #: would then hand to the next write, and the write would land on top of an
        #: unrelated survivor. Adversarial review found it on this lane's round 2, on
        #: the retirement path — which is the one that made a shrink routine.
        self._written = count(1)
        #: Every id this engine has held, written, or seen a question name as something
        #: an answer would retire. :meth:`answer` mints past it, which is the "globally
        #: non-reusing id source" ADR-0045 §4 asks a supersession's id to come from.
        #:
        #: **A set rather than an absence check, because absence is a fact about *now*
        #: and reuse is a fact about *ever*.** Three rounds of this lane's review each
        #: found a different way for a freed number to come back: sizing the store after
        #: shrinking it, minting the id an answer had just retired, and — the one only a
        #: record of the past can catch — minting an id that another *open* question has
        #: already told the user is "no longer held, so accepting would not touch it",
        #: whose later answer then retires the belief that took it. Each repair to the
        #: present state left the next case open, so what is kept is the history.
        self._spent: set[str] = set()
        #: The **read** parks this engine holds, by handle (ADR-0244 §5), populated by
        #: :meth:`park_read`. What ``resume``, ``pending_confirmations`` and
        #: ``cancel_read`` did with one left with them (ADR-0309 §5:1); what is left is
        #: :meth:`hold_confirmation_decision`'s binding, which ``grantable_decisions``
        #: reads.
        self.read_parked: dict[str, Confirmation] = {}
        #: The decision each **live** read park names, by handle (ADR-0244 §5). What
        #: §5's eighth ``grantable_decisions`` condition is decided from: a decision a
        #: park holds ``OPEN``, ``APPROVED`` or ``DENIED`` is not one the establishing
        #: act may ride. A cancellation removes the entry, because a cancelled park's
        #: decision is the one that returns to the listing.
        self._read_decisions: dict[str, str] = {}
        self.turn_outcome: TurnOutcome | None = None
        #: ADR-0264 §7's statement, for every outcome this engine composes itself, or
        #: ``None`` — the default — for :meth:`_outbound`'s fresh ``NOT_REACHED``.
        #:
        #: **A lever, because no sequence of surface calls reaches the other two
        #: members**: this double originates no model call and opens no channel, so
        #: nothing it does can establish a contact, and ``REACHED`` and
        #: ``INDETERMINATE`` would be unreachable in a consumer's test without one.
        #: They are what a surface rendering §7's statement most needs to be driven
        #: over — the browser's lane (#2237) and the terminal's alike — and the
        #: ``destinations`` and ``records`` a ``REACHED`` names come with the value a
        #: test hands over rather than from a reach this engine invents.
        #:
        #: **It is the value for a pass this engine composed and never a rewrite of a
        #: scripted one**: an outcome handed to :attr:`turn_outcome` is returned as the
        #: caller built it, that member included, exactly as every other member of a
        #: scripted outcome is.
        self.outbound_statement: OutboundStatement | None = None
        #: ADR-0260 §10's member, for every outcome this engine composes, or ``None`` —
        #: the default.
        #:
        #: **A lever, because no sequence of surface calls reaches any of the six**:
        #: this double wires no forecaster, services no read and records no
        #: ``ForecastDisposition``, so every member would be unreachable in a consumer's
        #: test without one — and they are exactly what a surface rendering §10's six
        #: fixed statements has to be driven over, on the terminal and on the browser
        #: alike (#2474).
        #:
        #: **``None`` is the honest default here and is not :attr:`outbound_statement`'s
        #: case.** §10 fixes the meaning of the absence — "``None`` means the servicing
        #: recorded no ``ForecastDisposition``, and means nothing else" — and a fake that
        #: services no read has recorded none, so filling one in would assert something
        #: no pass of this double established. What #2381 makes obligatory is a *true*
        #: value for a member a conforming engine always carries, not a value for one it
        #: leaves absent on every pass it takes.
        #:
        #: **A scripted outcome that already carries the member keeps what it carries**,
        #: which is :attr:`authorizations`' own arrangement: the caller stated the member
        #: and overwriting it would silently discard what they said.
        self.forecast_not_read: ForecastNotRead | None = None
        #: ADR-0261 §7's member, for every outcome this engine composes, or ``None`` —
        #: the default.
        #:
        #: :attr:`forecast_not_read`'s shape one vocabulary over, and a lever for its
        #: reason: **no sequence of surface calls on this double reaches any of the
        #: seven.** A withheld drive needs a ``PlanStore`` to refuse a ``→ RUNNING``
        #: claim on a liveness conjunct, which this engine never takes — so every member
        #: would be unreachable in a consumer's test, and the seven are exactly what a
        #: surface rendering §7's seven fixed statements has to be driven over, on the
        #: terminal and on the browser alike (ADR-0261 §13's L3).
        #:
        #: **``None`` is the honest default and §7 fixes what it means.** The member is
        #: non-``None`` "exactly on a turn that *returned* after a ``ClaimRefused`` whose
        #: post-refusal read established one of the seven states", and ``None`` on every
        #: other returned outcome — which is every pass this double takes.
        #:
        #: **A scripted outcome that already carries the member keeps what it carries**,
        #: which is :attr:`forecast_not_read`'s own arrangement.
        self.drive_withheld: DriveWithheld | None = None
        self.answered: AnswerOutcome | None = None
        # ADR-0250 §§12, 15's three operations, each defaulting to what the concrete
        # engine answers in that decision's M1: an empty listing, and the non-acting
        # member of each closed vocabulary.
        self.goal_summaries: list[GoalSummary] = []
        self.withdrawal: ClarificationWithdrawal = ClarificationWithdrawal.NOTHING_TO_WITHDRAW
        self.abandonment: GoalAbandonment = GoalAbandonment.NO_SUCH_GOAL
        #: ADR-0254 §11's two operations, answered from a real canonical store rather
        #: than from a scripted list — so a client's own paths are exercised against the
        #: store's real vocabulary: a revocation of a ``PROPOSED`` row answers
        #: ``NOT_AT_SOURCE`` here exactly as it does one store over, and a revoked row
        #: is absent from the next listing because ``standing`` no longer returns it.
        #: Seed it with :meth:`hold_authorization`.
        self.goal_authorizations = FakeGoalAuthorizationStore()
        #: The goal statement each listed authority is rendered by (ADR-0254 §11 — "the
        #: goal's **statement** (never its id)"), keyed by goal id. A goal absent here
        #: is the concrete engine's ``PlanStore.get_goal`` answering ``None``, which §11
        #: makes an **empty answer** rather than a raise, so this fake answers empty too.
        self.goal_statements: dict[str, str] = {}
        #: What :attr:`~ai_assistant.core.types.TurnOutcome.authorizations` carries on
        #: the next turn — ADR-0254 §11's announcement for the rows an act opened
        #: without a question. **Empty by default**, because a fake opens no row: §11
        #: makes the member empty "on every turn that opened none", so the default is
        #: the honest value and not a stand-in.
        self.authorizations: tuple[AuthorizationView, ...] = ()
        #: What :attr:`~ai_assistant.core.types.TurnOutcome.attempt_report` carries on
        #: a pass this engine **composed a reply for** — ADR-0262 §6's report — or
        #: ``None``, the default.
        #:
        #: **A lever, because no sequence of surface calls reaches a single member of
        #: it**: this double runs no verification phase and ends no attempt, so §6's
        #: "non-``None`` exactly on a turn that ended an attempt under §4" is a state
        #: nothing here can arrive at, and every one of the six
        #: :class:`~ai_assistant.core.types.AttemptOutcome` members a surface owes a
        #: fixed statement for would be unreachable in a consumer's test without one.
        #: That obligation is **not** optional and falls on **both** surfaces at once
        #: (ADR-0262 §11's L5), which is why the lever lands with the field rather than
        #: with its first renderer.
        #:
        #: **``None`` by default, because a fake ends no attempt**: §6 leaves the member
        #: absent on every turn that did not, so the default is the honest value and not
        #: a stand-in — :attr:`authorizations`'s ground one member over.
        #:
        #: **It is the value for a pass this engine composed and never a rewrite of a
        #: scripted one**: an outcome handed to :attr:`turn_outcome` already carrying a
        #: report keeps what it carries, exactly as a scripted
        #: :attr:`authorizations` does.
        self.attempt_report: AttemptReport | None = None
        #: What decides whether a listed row reads **live** or **lapsed** (ADR-0254 §16,
        #: ADR-0193 §9: one reading for a whole listing), and what stamps a withdrawal's
        #: ``settled_at``. Its own lever rather than :attr:`recipient_grant_clock`, and
        #: defaulted to the instant the shipped row builders are arranged around.
        self.authorization_clock: Callable[[], datetime] = lambda: AUTHORIZATION_NOW
        self._pending_authorizations: list[Authorization] = []
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
        #: The recipient-grant store ADR-0235 §7's two listings and its revocation
        #: relay, public and replaceable for :attr:`trail`'s reason: the states that
        #: matter here — a store at its ceiling, one already holding this subject,
        #: one that cannot be written — are facts about the **store**, and a fake
        #: engine holding a list of grants could only hand back what a test had
        #: already assembled. Seed it with ``hold`` or ``fail_writes``, or replace it
        #: with one built at a smaller ``max_outstanding``.
        #:
        #: **A whole ``RecipientGrantStore`` and never a ``RecipientGrants``**
        #: (ADR-0193 §1, ADR-0235 §4): the establishing act needs ``record``, and a
        #: fake offering the policy's narrow face would let a consumer's test
        #: authorise a send through an adapter.
        self.recipient_grants = FakeRecipientGrantStore()
        #: What stamps ``decided_at`` on an answer this engine records for an
        #: establishing act, and what ADR-0235 §1's expiry is compared against.
        #: Scriptable on :attr:`grant_clock`'s reason and **separate from it**,
        #: because recipient grants and source grants are two vocabularies and never
        #: one (ADR-0235 §7) — one clock over two stores is the shape that invites a
        #: test to reason about one from the other.
        self.recipient_grant_clock: Callable[[], datetime] = lambda: _AT
        #: What the user recorded about destinations (ADR-0238 §1), for ADR-0242 §2's
        #: three operations. A **whole** ``DestinationTrustStore`` for
        #: :attr:`recipient_grants`' reason one store over: the act needs ``record``,
        #: the listing needs ``live`` and revocation needs ``revoke``, and the states a
        #: consumer's test wants — a set already live, a store that cannot be written —
        #: are facts about the store. Seed it with ``hold`` or arm it with
        #: ``fail_writes``.
        self.destination_trust = FakeDestinationTrustStore()
        #: What stamps ``established_at`` on a trust record this engine mints, and the
        #: instant a revocation carries. **Separate from**
        #: :attr:`recipient_grant_clock` for ADR-0242 §4's two-vocabulary reason: one
        #: clock over two stores is the shape that invites a test to reason about one
        #: from the other.
        self.destination_trust_clock: Callable[[], datetime] = lambda: _AT
        #: Mints each trust record's id. **A fresh one per act**, as the production
        #: operations do: ADR-0238 §1 makes the store write-once, so an id derived from
        #: the *decision* would make a second act on one decision raise the duplicate-id
        #: refusal — and after a revocation that act is one ADR-0242 §1 admits, because
        #: the act is indifferent to a decision's ruling and resolution. A fake refusing
        #: it would be stricter than every conforming engine, and it would raise the
        #: **base** class where §2 fixes the subclass for a live duplicate, making the
        #: *already chosen* rendering unreachable in a consumer's test.
        self._trust_ids = count(1)
        #: The recorded ``CONFIRM`` each park stands for, by handle, where a test
        #: has bound one with :meth:`hold_confirmation_decision`. ``Confirmation``
        #: carries the **reduced** ``ConfirmationEgress`` and not the binding
        #: (ADR-0178 §5), and the establishing act transcribes its account and
        #: destination set from the binding — so the decision is *bound* rather than
        #: reconstructed here, since a fake assembling a call-level fact would be
        #: rendering the unobtainable bound ADR-0098 §6 forbids.
        self._parked_decisions: dict[str, PermissionDecision] = {}
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
        #: ADR-0293 §6's reader and §10's adapter. **The engine's own reader and
        #: writer** over this fake's chat space, so the interim — one activation at a
        #: time per conversation, and everything that waited taken in together as one
        #: input — and the bookkeeping are the engine's by construction rather than a
        #: copy kept in step by hand; what this fake supplies is the activation
        #: (:meth:`_read_in`), which runs as its turn calls do and answers with
        #: :attr:`turn_outcome` where one is scripted. Its reads are tasks held here,
        #: so none is collected mid-run.
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

    @staticmethod
    def _detached(statement: OutboundStatement) -> OutboundStatement:
        """One exact ``OutboundStatement`` of this value, sharing nothing with it.

        **The detachment ADR-0264 §7's "composed once per turn" needs of the object as
        well as of the computation.** ``frozen=True`` stops ``statement.reach = ...``
        but not ``statement.__dict__["reach"] = ...`` (ADR-0018 §3, §4), so an instance
        handed to two outcomes lets a consumer holding either rewrite what the other
        says this system did — the aliasing bug PR #2377's round 4 found in the concrete
        engine, which mints per pass for this reason. Every statement this engine hands
        out goes through here, so no two outcomes it returns can share one.

        **The value is read from the object's stored state and rebuilt as the base
        model**, rather than taken through ``model_copy``, ``model_dump`` or a plain
        attribute read. Each of those is a hook a subclassing caller controls: an
        override returning ``self`` reopens the aliasing above, and one intercepting
        field access hands back a value the object does not hold. ``__dict__`` is where
        a pydantic model keeps its fields, ``OutboundStatement.model_fields`` is read
        off the base class rather than the subject, and the result is validated exactly
        as a decoded frame's would be — so what an outcome carries is this value,
        typed as every consumer of the wire will see it.

        Args:
            statement: The value to detach, of this type or any subclass of it.

        Returns:
            An exact ``OutboundStatement`` equal to it.
        """
        state = object.__getattribute__(statement, "__dict__")
        return OutboundStatement(**{name: state[name] for name in OutboundStatement.model_fields})

    def _outbound(self) -> OutboundStatement:
        """ADR-0264 §7's statement for **one** outcome this engine composed.

        §7 leaves the member ``None`` "on exactly the passes that neither established a
        contact nor composed a reply", so every shape this double composes owes one —
        and ``NOT_REACHED`` is the honest default here rather than a stand-in: a fake
        originates no model call, services no read and opens no channel, so no pass of
        it can have reached outside this system. Issue #2381 is what this closes: a
        canonical fake that supplied none let a surface be written, tested green against
        it and never read the field at all, which is the failure the fake exists to
        prevent.

        A scripted value (:attr:`outbound_statement`) is detached per outcome for
        :meth:`_detached`'s reason, so scripting cannot reopen the aliasing the default
        closes.

        Returns:
            The scripted statement, detached, or a fresh ``NOT_REACHED``.
        """
        scripted = self.outbound_statement
        if scripted is None:
            return OutboundStatement(reach=OutboundReach.NOT_REACHED)
        return self._detached(scripted)

    def _stating(self, outcome: TurnOutcome) -> TurnOutcome:
        """Carry ADR-0264 §7's member on the outcome a turn call is about to return.

        **The one site of §7's rule for the three calls that take a scripted outcome**,
        so a synthesised outcome and a scripted one are held to it alike.
        :attr:`turn_outcome` is the lever every consumer drives a surface from, so an
        outcome scripted through it reaching a surface with ``reply`` and no statement
        is issue #2381 exactly, merely one lever further along: a renderer would be
        written, tested green against this double, and never read the field. §7 leaves
        the member ``None`` "on exactly the passes that neither established a contact
        nor composed a reply", and this engine establishes none — so an outcome that
        composed a reply owes one, and a fake handing back a shape no conforming engine
        produces is the looseness ADR-0026 §7 forbids.

        **A statement the caller stated is kept at its value and detached at its
        object** (:meth:`_detached`). A scripted outcome is one object this engine
        returns from every call, so carrying its statement through would put one
        instance on every outcome a consumer holds — which is the aliasing the default
        path closes, reached by the other lever.

        **A reply-less outcome is given none.** §7 admits both values on a pass that
        composed nothing — a recovered park carries ``None`` and ADR-0198 §1's
        restatement carries ``NOT_REACHED`` — and nothing in an outcome's shape tells
        the two apart, so filling one in there would assert what the caller did not.

        **The outcome's other members are carried across untouched, and that includes
        their objects**: a scripted ``turn`` or ``routed`` is the same instance on every
        outcome this engine returns, exactly as it is today
        (`#2386 <https://github.com/leonapivato/ai-assistant/issues/2386>`_). What is
        detached here is the member this decision makes load-bearing, and widening that
        to the whole outcome is a change to what scripting means rather than this lane's.

        **ADR-0260 §10's member rides the same site, on ADR-0254 §11's terms rather
        than §7's**: a scripted outcome carrying the member keeps it, and the attribute
        fills in only where the outcome states none. §10 fixes the absence's meaning —
        ``None`` "means the servicing recorded no ``ForecastDisposition``, and means
        nothing else" — so there is nothing to synthesise for a pass that serviced no
        read, and the member is a lever rather than a default for the reason
        :attr:`forecast_not_read` records.

        **ADR-0261 §7's member rides the same site, on ADR-0260 §10's terms exactly**: a
        scripted outcome carrying the member keeps it, and the attribute fills in only
        where the outcome states none. §7 fixes the absence's meaning — the member is
        non-``None`` "exactly on a turn that *returned* after a ``ClaimRefused``" — so
        there is nothing to synthesise for a pass that met no refusal, and the member is
        a lever rather than a default for the reason :attr:`drive_withheld` records.

        **ADR-0254 §11's announcement rides the same site**, and its default is the
        opposite one for the opposite reason: §7's member states a fact about the pass
        and so must be filled in, while §11's states *which rows this turn opened* and a
        fake opens none — so ``()`` is the honest value and a scripted
        :attr:`authorizations` is carried through unchanged. A scripted **outcome** that
        already carries the member keeps what it carries: the announcement is
        transcribed from rows, so a caller who stated them on the outcome has stated the
        rows, and overwriting that with this engine's attribute would silently discard
        the arrangement (`#2386 <https://github.com/leonapivato/ai-assistant/issues/2386>`_
        is the aliasing note one member over and is not what this is).

        Args:
            outcome: The outcome this call is about to return.

        Returns:
            The outcome, carrying §7's member where the pass composed a reply and
            §11's where this engine was scripted with one.
        """
        stated = outcome.outbound_statement
        announced = outcome.authorizations or self.authorizations
        reported = self._reported(outcome)
        forecast = outcome.forecast_not_read or self.forecast_not_read
        withheld_drive = outcome.drive_withheld or self.drive_withheld
        if (
            stated is None
            and outcome.reply is None
            and announced == outcome.authorizations
            and reported == outcome.attempt_report
            and forecast == outcome.forecast_not_read
            and withheld_drive == outcome.drive_withheld
        ):
            return outcome
        carried = {name: getattr(outcome, name) for name in TurnOutcome.model_fields}
        carried["authorizations"] = announced
        carried["attempt_report"] = reported
        carried["forecast_not_read"] = forecast
        carried["drive_withheld"] = withheld_drive
        if stated is None and outcome.reply is None:
            return TurnOutcome(**carried)
        statement = self._outbound() if stated is None else self._detached(stated)
        return TurnOutcome(**{**carried, "outbound_statement": statement})

    def _reported(self, outcome: TurnOutcome) -> AttemptReport | None:
        """ADR-0262 §6's report for the outcome a turn call is about to return.

        **The lever reaches exactly the one shape a conforming engine puts a report
        on**, and the enumeration is §6's own: the member is ``None`` on "a turn that
        engaged no goal, a routed operation (ADR-0197 §7), ADR-0198 §1's restatement,
        and every turn whose attempt stayed live". The last two are the caller's — the
        default is ``None`` and a consumer sets the lever for the turn it means — and
        the first two are shapes, so they are decided here:

        * a **routed** pass carries none, whatever prose it has. It "mints no goal,
          assembles no context and makes no plan" (ADR-0197 §8), so there is no attempt
          for a report to be about; §6 names it in terms.
        * a pass whose :attr:`TurnOutcome.turn` is ``None`` carries none. All three such
          shapes made no ``Planner.plan`` call — a recovered park, a routed pass and an
          undecided turn — and §6's rule is stated over a turn that *ended an attempt*
          under §4, whose first condition is a **completed reply** that such a pass did
          not compose.
        * a pass that composed no reply, **or whose reply did not complete**, carries
          none. §4's first ending condition is *"a ``ComposedReply`` carrying text and
          **not degraded**"* (ADR-0173 §6), so a truncated or failed composition ends no
          attempt however much text reached the user.
        * a pass carrying a **clarification** carries none. That member is "the question
          **this turn raised**" and a question exists only where the store accepted one
          (ADR-0250 §10), so the attempt stands ``AWAITING_CLARIFICATION`` — which §4's
          **second** ending condition names among the three paused states an attempt may
          not end from. ADR-0250 §10's *"A turn that raised a question drives no step of
          its plan and produces no effect"* is the same fact from the other side.
        * a pass whose **visible execution holds a non-terminal step** carries none.
          §4's **third** ending condition is that "every step of every execution it
          names stands ``SUCCEEDED``, ``FAILED`` or ``SKIPPED``", and
          :attr:`StepOutcome.state` puts one such execution on the outcome whole — so a
          step standing ``PENDING``, ``AWAITING_APPROVAL``, ``RUNNING`` or
          ``INDETERMINATE`` is decisive on its own. **It is a one-way test and not the
          store's**: an attempt may name executions this outcome does not show, so a
          clean visible execution proves nothing and the caller still decides. That
          asymmetry is the right one — the fake refuses only what it can *see* is
          unreachable.

        **Taken as one pass over §4's three conditions rather than one predicate per
        finding.** Each is written beside the clause it comes from and the admitted
        statuses are named in :data:`_ENDING_ADMITS`, which
        ``tests/testing/test_fake_engine_attempt_report.py`` pins against §4's own
        enumeration — so a later decision moving that set fails a test here rather than
        leaving this gate quietly short a status.

        **A fake that filled the member in anywhere else would hand back a shape no
        conforming engine produces**, which is the looseness ADR-0026 §7 forbids and
        which this method's caller already refuses one member over.

        **And a report a caller scripted onto an ineligible outcome is refused rather
        than dropped.** Dropping it would pass the arrangement mistake silently and
        leave the consumer's test green against an outcome it believed it had built;
        refusing says which of §6's shapes the outcome actually is. That is
        :attr:`authorizations`'s *"a scripted outcome keeps what it carries"* held to
        its own ground — it keeps what it carries on a pass that **could** carry it, and
        this is not one.

        **And ``CANCELLED`` is refused outright rather than carried.** ADR-0262 §4 is
        explicit that it "is reached by no limb" of the comparison and that "**no lane
        writes ``AttemptOutcome.CANCELLED`` from this phase**" — a cancelled attempt is
        ADR-0261 §2's act, and ADR-0249 §5's "no transition leaves a terminal member" is
        what keeps it out of reach. So a report naming it is a state no engine reaches,
        and a double that let a consumer arrange one would certify that consumer against
        a seventh fixed statement §6 does not authorise. This is
        :meth:`FakeToolRegistry.register`'s rule read one seam over: the single
        arrangement mistake a consumer could plausibly make, refused rather than passed
        silently. **The type still admits the member** — it is handed one rather than
        computing one, and narrowing it here would be this fake policing a value
        ADR-0261 owns — which is why the refusal is on the *arrangement* and not on
        :class:`AttemptReport`.

        Args:
            outcome: The outcome this call is about to return.

        Returns:
            The report this pass carries, or ``None``.

        Raises:
            ValueError: If the report this pass would carry names ``CANCELLED``.
        """
        eligible = (
            # The two structural preconditions: a pass that made a plan, and one that
            # took no route.
            outcome.turn is not None
            and outcome.routed is None
            # §4's condition 1 — a reply that **completed**.
            and outcome.reply is not None
            and not outcome.reply_degraded
            # §4's condition 2 — the attempt is not paused. ``clarification`` is the one
            # of its three states the outcome names; the ``AWAITING_APPROVAL`` step it
            # also excludes is a *status*, so condition 3's sweep is what catches it.
            and outcome.clarification is None
            # §4's condition 3 — every step of every execution the attempt names stands
            # terminal. The outcome shows one execution, which is the whole of what a
            # double can see, and a non-terminal step there is decisive on its own.
            and not (
                outcome.step is not None
                and any(step.status not in _ENDING_ADMITS for step in outcome.step.state.steps)
            )
        )
        reported = outcome.attempt_report or (self.attempt_report if eligible else None)
        if reported is None:
            return None
        if not eligible:
            msg = (
                "this pass ended no attempt, so it carries no report: a report is "
                "non-None exactly on a turn that ended one, and §4's three conditions "
                "for that are a reply that completed, an attempt that is not paused, "
                "and every step of it standing SUCCEEDED, FAILED or SKIPPED — on a "
                "pass that planned and took no route (ADR-0262 §4, §6)"
            )
            raise ValueError(msg)
        if reported.outcome is AttemptOutcome.CANCELLED:
            msg = (
                "no attempt report names CANCELLED: that member is reached by no limb of "
                "the comparison and no lane writes it from this phase, so a turn carrying "
                "one is a shape no conforming engine returns (ADR-0262 §4, §6)"
            )
            raise ValueError(msg)
        return reported

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
        result = _event_result(target, ActivationEnding.DONE)
        activation.observe(result)
        return result

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
        no membership, digest or delivery, so forgetting its conversation cannot take
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
        if (
            isinstance(activation.trigger, RecordedChannelTrigger)
            and isinstance(activation.trigger.payload, RecordedSpeechInput)
            and activation.outcome is not None
        ):
            self.deliveries[episode] = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)

    def hold_confirmation_decision(self, handle: str, decision: PermissionDecision) -> None:
        """Bind a recorded ``CONFIRM`` to a park, so an establishing act can ride it.

        **A lever, because no sequence of surface calls reaches the state**, which is
        :meth:`park_read`'s own reason one record over. ADR-0235 §2 has the act ride *the
        answer to a recorded ``CONFIRM``*, and
        :meth:`~ai_assistant.core.types.RecipientGrant.established_from` transcribes
        the grant's ``tool``, ``account`` and destination set **from that decision**
        — while a :class:`~ai_assistant.core.types.Confirmation` carries the reduced
        ``ConfirmationEgress`` and no binding at all (ADR-0178 §5). So a test that
        means to drive the act hands over the decision it recorded, rather than
        having this fake assemble a call-level fact it was never given (ADR-0098 §6).

        The decision is **not** appended to :attr:`trail` here: a park that wrote a
        row would change what ``recent_decisions`` says for every consumer that never
        asked about recipient grants. A test that wants it in the trail — which the
        establishing path needs, because the answer ``resolves`` it — records it
        there itself, exactly as it seeds every other row.

        **It binds a read park exactly as it binds a step's** (ADR-0244 §5). The act
        rides a read park's answer "exactly as ADR-0235 §2 rules it, unchanged", and a
        read park this fake holds no decision for meets §2's binding refusal on its
        first shape — there is no ``EgressBinding`` to transcribe from — so a consumer
        driving the act's *successful* path over a parked read hands the decision over
        here, as it does for a step.

        Args:
            handle: The continuation handle the park is answered by.
            decision: The recorded ``CONFIRM``, as the trail holds it.
        """
        self._parked_decisions[handle] = decision
        if handle in self.read_parked:
            # **ADR-0244 §5's eighth condition becomes reachable the moment a read park
            # names a decision.** A fake that bound one and went on offering it to
            # ``grantable_decisions`` would certify a consumer against an engine that
            # refuses — and against the very failure §5 exists to prevent, a user
            # performing the act that changes nothing about this lookup while the
            # lookup's own question stands unanswered beside it.
            self._read_decisions[handle] = decision.id

    def _recipient_now(self) -> datetime:
        """The guarded reading of :attr:`recipient_grant_clock` (ADR-0026 §2, §4).

        **Guarded at the read and not at construction, which is this attribute's
        own shape rather than an exception to the rule.**
        :func:`~ai_assistant.core.clock.checked_clock` says to wrap "where the clock
        is stored", and on this class the clock is stored where a *test* replaces it
        — it is a public lever, so a wrapper installed in ``__init__`` would be
        thrown away by the next assignment and the guard would be there or not
        depending on whether a case used the lever.

        The translation is :meth:`StepRunner._now`'s, so the fake refuses what the
        concrete engine refuses with the type it refuses it with: a consumer's test
        against a non-conforming clock must not pass here and fail against a hub.

        Raises:
            PlanningError: If the reading is not a conforming one — naive,
                indeterminate, or outside the localizable range.
        """
        try:
            return checked_clock(self.recipient_grant_clock, owner="FakeAssistantEngine")()
        except ClockReadingError as exc:
            msg = f"the recipient-grant clock returned a non-conforming reading: {exc}"
            raise PlanningError(msg) from exc

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

    async def goals(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[GoalSummary, ...]:
        """Return the scripted goal listing (ADR-0250 §15).

        Empty by default, which is what the concrete engine answers in ADR-0250
        §19's M1 — that lane changes no behaviour, and ``PlanStore`` carries no goal
        listing for the operation to read.

        Args:
            limit: How many summaries to return.
            offset: How many to skip.

        Returns:
            The scripted page, sliced by the paging arguments.
        """
        self._check_page("goals", limit=limit, offset=offset)
        return self._checked(tuple(self.goal_summaries[offset : offset + limit]), "goals")

    async def withdraw_clarification(self, question_id: Identifier, /) -> ClarificationWithdrawal:
        """Return what became of a withdrawal (ADR-0250 §12).

        ``NOTHING_TO_WITHDRAW`` unless a consumer scripts otherwise, which is both
        the vocabulary's non-acting member and what an unknown id answers — "an
        unknown id is ``NOTHING_TO_WITHDRAW`` and never a raise".

        Args:
            question_id: The clarification to withdraw.

        Returns:
            The scripted answer.
        """
        named = identifier(question_id, name="question_id")
        check_arguments(
            "withdraw_clarification", max_bytes=self._max_payload_bytes, question_id=named
        )
        self.calls.append(("withdraw_clarification", {"question_id": named}))
        return self.withdrawal

    async def abandon_goal(self, goal_id: Identifier, /) -> GoalAbandonment:
        """Return what became of an abandonment (ADR-0250 §12).

        ``NO_SUCH_GOAL`` unless a consumer scripts otherwise, which is the
        vocabulary's non-acting member and what an unknown id answers.

        Args:
            goal_id: The goal to abandon.

        Returns:
            The scripted answer.
        """
        named = identifier(goal_id, name="goal_id")
        check_arguments("abandon_goal", max_bytes=self._max_payload_bytes, goal_id=named)
        self.calls.append(("abandon_goal", {"goal_id": named}))
        return self.abandonment

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
        """List what is held, as summaries that carry counts and no citations."""
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
        matching = [
            _summary_of(belief)
            for belief in self.beliefs_held.values()
            if (selected_bands is None or belief.band in selected_bands)
            and (selected_kinds is None or belief.kind in selected_kinds)
        ]
        return self._checked(tuple(matching[offset : offset + limit]), "beliefs")

    async def belief(self, record_id: Identifier) -> Belief | None:
        """Read one belief with its citations, or ``None`` where none is held."""
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

    # --- the deferred-question surface ------------------------------------

    async def questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions waiting for an answer."""
        self._check_page("questions", limit=limit, offset=offset)
        held = tuple(self.questions_open.values())
        return self._checked(held[offset : offset + limit], "questions")

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """List the questions whose answer was begun and never recorded."""
        self._check_page("interrupted_questions", limit=limit, offset=offset)
        held = tuple(self.questions_interrupted.values())
        return self._checked(held[offset : offset + limit], "interrupted_questions")

    async def answer(self, question_id: Identifier, *, accept: bool) -> AnswerOutcome:
        """Answer one question, applying it or declining it.

        **What an accepted answer writes carries the proposal's own origin, and what it
        authorises is retired.** ADR-0189 §2 defines a ``Question``'s ``attestation`` and
        ``rests_on_recorded_external_content`` as facts about *the record acceptance
        would write*, so an answer that dropped them would leave this fake holding a
        belief whose origin differs from the question it came from. And ADR-0078 §8
        makes ``retires`` "the exact scope the answer authorises" rather than
        decoration, so an answer that left a named conflict live would apply a
        correction and keep the thing it corrected.

        Neither could arise while :meth:`ask` fixed the band at ``ASSERTED`` and built
        ``retires=()``: no question could carry an attestation and none could name a
        retirement. Making both scriptable (#1523) is what puts an engine on the far
        side of them, and this is the whole of what that costs — a working in-memory
        engine is the point of this class, and an ``answer`` that wrote the wrong record
        would let a conformance suite pass against behaviour no real engine has.

        The externality answer is forwarded as the ``Provenance`` field it came from
        rather than as the answer it produced, because :meth:`hold` derives the answer
        through :func:`~ai_assistant.core.types.rests_on_recorded_external_content` and
        the band guards it there: a stray ``True`` on a proposal whose band makes the
        predicate ``False`` is discarded by the classifier, which is ADR-0072 §4 and
        ADR-0106 §2 doing their job rather than this method second-guessing them.

        **A retirement that no longer resolves retires nothing**, which is not a special
        case but the same rule: the retirement names a ``record_id`` either way, and
        where ``MemoryStore.get`` hid a closed window (ADR-0045 §6) the record is
        already gone, so discarding by id is idempotent. The scope is what the answer
        *names*, not what the projection managed to resolve.

        **The written id comes from a counter and not from the store's size**, because
        this method now shrinks the store. With ``rec-1`` and ``rec-2`` held, retiring
        ``rec-1`` and sizing the next id would mint ``rec-2`` and write on top of the
        unrelated survivor — an answer destroying a record outside the scope it
        presented, which is the opposite of ADR-0078 §8's guarantee.

        **And it mints past every id this engine has ever spent** — see
        :attr:`_spent` — not merely past the ones live at this instant. That is
        ADR-0045 §4's rule about a correction's id, read one implementation over: there
        a superseded target is *retained* with a closed window ("``T`` stays on disk with
        a closed window — retained, off the read path"), so §4's freshly-minted id must
        be "absent from the store" with "the retained target ``T`` included", and the new
        record "no longer borrows ``T``'s id". This engine has no windows, so retiring
        removes the record outright and any check against the *present* store is
        satisfied by a number that has just been freed.

        Three review rounds each found a different way for that to bite, and the last is
        why the reservation is a history rather than a wider snapshot: a question still
        open may already have told the user that some id is "no longer held, so accepting
        would not touch it", and if a later answer mints that id, answering the first
        question then destroys the belief that took it. No fact about the store at mint
        time can see that coming; a record of what has been named can.
        """
        named = identifier(question_id, name="question_id")
        check_arguments(
            "answer", max_bytes=self._max_payload_bytes, question_id=named, accept=accept
        )
        self.calls.append(("answer", {"question_id": named, "accept": accept}))
        if self.answered is not None:
            return self._checked(self.answered, "answer")
        question = self.questions_open.pop(named, None)
        if question is None:
            return self._checked(
                AnswerOutcome(kind=AnswerKind.NOT_OPEN, question_id=named), "answer"
            )
        if not accept:
            return self._checked(
                AnswerOutcome(kind=AnswerKind.REJECTED, question_id=named), "answer"
            )
        for retirement in question.retires:
            self.beliefs_held.pop(retirement.record_id, None)
        record_id = f"rec-{next(self._written)}"
        while record_id in self._spent:
            record_id = f"rec-{next(self._written)}"
        self.hold(
            record_id,
            content=question.content,
            kind=question.kind,
            band=question.band,
            attestation=question.attestation,
            derived_from_external=question.rests_on_recorded_external_content,
        )
        return self._checked(
            AnswerOutcome(kind=AnswerKind.APPLIED, question_id=named, record_id=record_id), "answer"
        )

    async def forget_question(self, question_id: Identifier) -> bool:
        """Destroy one question, reporting whether there was one to destroy."""
        named = identifier(question_id, name="question_id")
        check_arguments("forget_question", max_bytes=self._max_payload_bytes, question_id=named)
        self.calls.append(("forget_question", {"question_id": named}))
        gone = (
            self.questions_open.pop(named, None)
            or self.questions_interrupted.pop(named, None)
            or self.questions_settled.pop(named, None)
        )
        return self._checked(gone is not None, "forget_question")

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
            # message answering it is written, which is after its own run has ended.
            if (reading := self._reader.working(named)) is not None and reading not in running:
                running.append(reading)
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
            self.deliveries.pop(episode, None)
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

        Each running activation by its id, and the activation the chat's reader has an
        input in for, beside a count that moves at each end and at each of the
        reader's admissions and replies — the account the change stream pushes the
        current state from (ADR-0296 §4:9).
        """
        running: dict[str, list[str | None]] = {}
        for one in self._running_activations:
            if one.conversation_id is not None:
                running.setdefault(one.conversation_id, []).append(one.activation_id)
        reader = self._reader.activity()
        for conversation_id, (_, reading) in reader.items():
            if reading is None:
                continue
            held = running.setdefault(conversation_id, [])
            if reading not in held:
                held.append(reading)
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
        """Admit one activation for the reader's input, then write what it ends with.

        The input is admitted as a typed message on the conversation's channel, with
        the id the reader minted, and is running — "working…", and reachable by a
        stop — from then on. **Its first step marks the messages taken in** (ADR-0293
        §6:8); it then runs on what it marked alone, as a turn call here runs, and its
        episode is captured as theirs is. What it ends with is written into the
        conversation by the engine's own adapter and writer: the reply, or *couldn't
        finish* listing what did happen (§10:1, §10:2).

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
        outcome: TurnOutcome | None = None
        failure: BaseException | None = None
        try:
            await self._reader.take_in(taken, into=marked)
            if not marked:
                msg = "the reader's input was not taken in"
                raise RuntimeError(msg)
            # ADR-0297 §4: a stop marked while the input was being taken in starts
            # nothing after it — no understanding, no reply — and the pass ends.
            if not activation.stopped:
                outcome = self._chat_outcome(taken.narrowed(marked), activation)
        except BaseException as exc:
            failure = exc
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
        if not marked or activation.stopped:
            return bool(marked)
        reply = chat_reply(None if failure is not None else outcome, effects=chat_effects(outcome))
        # A reply the store would not take is lost, as the engine loses it: the
        # activation still took its input in, so the reader goes on to what waited.
        with contextlib.suppress(ConversationStoreError):
            await self._chat_writer.send(conversation_id, reply)
        return True

    def _chat_outcome(self, taken: ChatInput, activation: FakeActivation) -> TurnOutcome:
        """The turn the reader's input runs as: :attr:`turn_outcome`, or a composed reply."""
        conversation_id = taken.conversation_id
        activation.resolved(conversation_id)
        if conversation_id in self.activity:
            self.activity[conversation_id] = self._tick()
        activation.understand()
        text = taken.text
        outcome = self.turn_outcome or TurnOutcome(
            turn=_turn(text),
            conversation_id=conversation_id,
            reply=f"This fake engine composed no real answer to {text.strip()!r}.",
        )
        if outcome.conversation_id is None:
            outcome = outcome.model_copy(update={"conversation_id": conversation_id})
        outcome = self._stating(outcome)
        activation.observe(outcome)
        return outcome

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

    # --- the recipient-grant surface (ADR-0235 §3, §7) ---------------------

    async def grantable_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """List the recorded ``CONFIRM``s an establishing act may ride (ADR-0235 §3).

        **The conditions and the window rule are implemented rather than assumed
        away**, which is what a canonical fake owes: the shared suite holds this
        class to the same clauses it holds every other implementation to, and a fake
        that returned whatever a test had seeded would certify a consumer against a
        hub answering a different question. In particular a decision sharing the
        oldest returned row's ``decided_at`` is **not** offered on an incomplete
        window, and a decision a park holds — one carrying a ``step_id`` or an
        ``execution_id`` — is never offered at all.
        """
        positive_page_argument(limit, name="limit")
        check_arguments("grantable_decisions", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("grantable_decisions", {"limit": limit}))
        rows = await self.trail.recent(limit=limit)
        now = self._recipient_now()
        resolved = {row.resolves for row in rows if row.resolves is not None}
        complete = len(rows) < limit
        oldest = rows[-1].decided_at if rows else None
        offerable = [
            row
            for row in rows
            if rides_an_establishing_act(row, now=now)
            and row.id not in resolved
            and (complete or oldest is None or row.decided_at > oldest)
            # ADR-0244 §5's **eighth** condition, evaluated after §3's seven and in that
            # position — so a decision a read park holds is answered through ``resume``
            # and is not offered beside an act that resumes nothing.
            and not self._park_excludes(str(row.id))
        ]
        return self._checked(tuple(offerable), "grantable_decisions")

    async def establish_recipient_grant(
        self, decision_id: DurableIdentifier, *, expires_at: UtcInstant
    ) -> RecipientGrant:
        """Answer a recorded ``CONFIRM`` no park holds and record the grant.

        The seven availability conditions in ADR-0235 §3's own order, so that where
        more than one fails the first is the one named. This engine holds no
        ``ActionPolicy``, so the ruling it records is the ``ALLOW`` an approving
        answer produces — a client's ``PermissionDeniedError`` path is reached by
        seeding a decision the policy would decline in a hub, and is not something
        this double invents a lever for.
        """
        named = identifier(decision_id, name="decision_id")
        until = utc_instant(expires_at, name="expires_at")
        check_arguments(
            "establish_recipient_grant",
            max_bytes=self._max_payload_bytes,
            decision_id=named,
            expires_at=until,
        )
        self.calls.append(
            ("establish_recipient_grant", {"decision_id": named, "expires_at": until})
        )
        confirmed = await self._offerable_decision(named)
        decided_at = self._recipient_now()
        if until <= decided_at:
            msg = (
                f"a standing recipient grant expires strictly after the answer that "
                f"establishes it; {until.isoformat()} is at or before "
                f"{decided_at.isoformat()}, the instant this answer would carry, so nothing "
                f"was recorded (ADR-0235 §1)"
            )
            raise UngrantableActError(msg)
        answer = PermissionDecision.from_confirmation(
            confirmed, _approving(confirmed), id=f"decision-{named}-answer", decided_at=decided_at
        )
        await self.trail.record(answer)
        grant = RecipientGrant.established_from(
            confirmed, answer, id=f"recipient-grant-{named}", expires_at=until
        )
        await self.recipient_grants.record(grant)
        return self._checked(grant, "establish_recipient_grant")

    async def standing_recipient_grants(self) -> tuple[RecipientGrant, ...]:
        """List every standing recipient grant that is live now (ADR-0235 §7).

        Read from :attr:`recipient_grants` and from nothing else, so liveness is the
        store's and is never re-derived from the history — the substitution ADR-0235
        §7 forbids at every surface.
        """
        self.calls.append(("standing_recipient_grants", {}))
        return self._checked(
            tuple(await self.recipient_grants.standing()), "standing_recipient_grants"
        )

    async def recent_recipient_grants(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecipientGrant, ...]:
        """List the recipient-grant store's own history, newest first (ADR-0235 §7).

        Granting and revoking records alike, and **no liveness**: a record here says
        an act happened, never that it still stands.
        """
        positive_page_argument(limit, name="limit")
        check_arguments("recent_recipient_grants", max_bytes=self._max_payload_bytes, limit=limit)
        self.calls.append(("recent_recipient_grants", {"limit": limit}))
        return self._checked(
            tuple(await self.recipient_grants.recent(limit=limit)), "recent_recipient_grants"
        )

    async def revoke_recipient_grant(self, grant_id: DurableIdentifier) -> RecipientGrant | None:
        """Withdraw one standing recipient grant, or report there was none (ADR-0235 §7).

        The revoking record transcribes the outstanding record's ``tool``,
        ``account`` and ``destinations`` verbatim, and a refusal met while the grant
        is no longer outstanding answers ``None`` — this method's own second branch
        reached late rather than a third outcome.
        """
        named = identifier(grant_id, name="grant_id")
        check_arguments("revoke_recipient_grant", max_bytes=self._max_payload_bytes, grant_id=named)
        self.calls.append(("revoke_recipient_grant", {"grant_id": named}))
        outstanding = await self.recipient_grants.outstanding(named)
        if outstanding is None:
            return None
        record = RecipientGrant(
            id=f"revocation-{named}",
            tool=outstanding.tool,
            account=outstanding.account,
            destinations=outstanding.destinations,
            decided_at=self._recipient_now(),
            expires_at=outstanding.expires_at,
            revokes=outstanding.id,
        )
        try:
            await self.recipient_grants.record(record)
        except InvalidRecipientGrantError:
            if await self.recipient_grants.outstanding(named) is None:
                return None
            raise
        return self._checked(record, "revoke_recipient_grant")

    # --- the goal-authorization surface (ADR-0254 §11) -----------------------

    def hold_authorization(self, row: Authorization, *, goal_statement: str | None = None) -> None:
        """Seed one record, and the statement its goal is rendered by.

        **Written through the store's own ``record``**, so a row this fake will not
        accept is one the real store would not accept either — the shapes ADR-0254 §1
        forbids are refused here at seeding rather than discovered at the listing.

        Args:
            row: The record to hold.
            goal_statement: What §11's listing renders the goal as. Defaults to a
                statement derived from the goal's id; pass ``None`` explicitly and then
                delete the key to exercise the goal the plan store does not hold, which
                §11 makes an **empty answer**.
        """
        self.goal_statements[row.goal] = goal_statement or f"work on {row.goal}"
        self._pending_authorizations.append(row)

    async def standing_authorizations(self, goal_id: Identifier) -> tuple[AuthorizationView, ...]:
        """What one goal's recorded acts still authorise (ADR-0254 §11).

        The ``ESTABLISHED`` rows of that goal, **live and lapsed**, read from
        ``standing`` and projected — never a ``PROPOSED``, ``DECLINED``, ``EXPIRED``,
        ``REVOKED`` or ``SUPERSEDED`` one, because ``standing`` does not offer them.

        **One clock reading for the whole listing** (§16), taken here because
        ``standing`` evaluates no liveness and reports none — and taken **after** the
        snapshot, which is where the concrete engine takes it and for its reason: a row
        settled while ``standing`` is suspended comes back carrying a ``settled_at``
        after a reading taken first, and §1's predicate would then report a live row as
        lapsed. A fake that judged over a different boundary would let a consumer's test
        pass here and fail against a hub, which is the looseness ADR-0026 §7 forbids.
        Adversarial and architecture review, round 3.

        **A goal this fake holds no statement for is an empty answer and not a raise**,
        which is what the concrete engine does where ``PlanStore.get_goal`` answers
        ``None`` — and, as there, it is answered **before** the clock is read, so the
        clause holds on a deployment whose clock is non-conforming.
        """
        named = identifier(goal_id, name="goal_id")
        check_arguments("standing_authorizations", max_bytes=self._max_payload_bytes, goal_id=named)
        self.calls.append(("standing_authorizations", {"goal_id": named}))
        await self._flush_authorizations()
        statement = self.goal_statements.get(named)
        if statement is None:
            return self._checked((), "standing_authorizations")
        rows = await self.goal_authorizations.standing(named)
        reading = self._authorization_now()
        return self._checked(
            tuple(
                view_of(row, goal_statement=statement, live=is_live(row, reading)) for row in rows
            ),
            "standing_authorizations",
        )

    async def revoke_authorization(
        self, authorization_id: DurableIdentifier
    ) -> AuthorizationSettlement:
        """Withdraw one standing authorization (ADR-0254 §11).

        ``settle`` to ``REVOKED`` on ADR-0254 §1's one edge out of ``ESTABLISHED``, its
        answer returned **unmapped**. **No call raises**: an unknown id is
        ``NO_SUCH_AUTHORIZATION`` and a row not at that edge's source is
        ``NOT_AT_SOURCE``, which is
        ``AssistantEngineContract::test_a_refusal_is_a_result_and_not_an_exception``'s
        rule. **``WOULD_DUPLICATE`` is unreachable here** — it is reachable only on a
        settlement **to** ``ESTABLISHED`` — and this fake maps nothing, so a client
        tested against it meets exactly the vocabulary the hub sends.
        """
        named = identifier(authorization_id, name="authorization_id")
        check_arguments(
            "revoke_authorization", max_bytes=self._max_payload_bytes, authorization_id=named
        )
        self.calls.append(("revoke_authorization", {"authorization_id": named}))
        await self._flush_authorizations()
        return await self.goal_authorizations.settle(
            named,
            to=AuthorizationDisposition.REVOKED,
            settled_at=self._authorization_now(),
        )

    async def _flush_authorizations(self) -> None:
        """Write the rows :meth:`hold_authorization` took, once.

        Seeding is synchronous because a test's arrangement is, and ``record`` is
        ``async`` because a store is — so the write is deferred to the first operation
        that reads. It is **not** re-run per row on later calls: the queue is drained.
        """
        while self._pending_authorizations:
            await self.goal_authorizations.record(self._pending_authorizations.pop(0))

    def _authorization_now(self) -> datetime:
        """This engine's one clock reading for an authorization operation.

        **Its own lever and not :attr:`recipient_grant_clock`**, for that attribute's
        own stated reason one store over: one clock over two vocabularies is the shape
        that invites a test to reason about one and move the other. It defaults to
        :data:`~ai_assistant.testing.AUTHORIZATION_NOW`, the instant the shipped row
        builders are arranged around, so a row built with ``authorization(...)`` and a
        listing taken from this engine sit on **one** timeline rather than two that
        happen to agree.

        Guarded at the read rather than at construction, exactly as
        :meth:`_recipient_now` is and for its reason: the attribute is a public lever a
        case replaces, so a wrapper installed in ``__init__`` would be thrown away by
        the next assignment.

        Raises:
            PlanningError: If the clock's reading is not conforming.
        """
        try:
            return checked_clock(self.authorization_clock, owner="FakeAssistantEngine")()
        except ClockReadingError as exc:
            raise PlanningError(str(exc)) from exc

    # --- the destination-trust surface (ADR-0242 §2, §4) --------------------

    async def establish_destination_trust(
        self, decision_id: DurableIdentifier
    ) -> DestinationTrustRecord:
        """Record the user's choice over a recorded decision's destinations (ADR-0242 §1).

        **The real conditions, in ADR-0242 §1's own order**, against
        :attr:`trail` — not a scripted outcome — so a consumer's test drives the same
        three refusals the production engine raises and reads each from its type. The
        destination set is transcribed from the binding's own
        ``canonical_destination_set`` and never rebuilt here, and **nothing is written
        on any refusal**.

        Raises:
            ValueError: If ``decision_id`` is blank or unwritable.
            UntrustableDestinationError: If any of the three conditions fails.
            DuplicateDestinationTrustError: If a live record already names this set.
            InvalidDestinationTrustError: If the store refused or could not be written.
        """
        named = identifier(decision_id, name="decision_id")
        check_arguments(
            "establish_destination_trust", max_bytes=self._max_payload_bytes, decision_id=named
        )
        self.calls.append(("establish_destination_trust", {"decision_id": named}))
        decision = await self.trail.get(named)
        if decision is None:
            msg = (
                f"no decision {named!r} is recorded, so there is no destination set to "
                f"transcribe and nothing was recorded (ADR-0242 §1)"
            )
            raise UntrustableDestinationError(msg)
        binding = decision.egress_binding
        if not isinstance(binding, EgressBinding):
            msg = (
                f"decision {named!r} records no whole egress binding, so the destination set "
                f"this act would be over is not on the row; nothing was recorded (ADR-0242 §1)"
            )
            raise UntrustableDestinationError(msg)
        if binding.planned_with_external_content:
            msg = (
                f"decision {named!r} records a call planned over recorded external content, "
                f"and trust recorded from such a call is the loop closing on itself; nothing "
                f"was recorded (ADR-0242 §1)"
            )
            raise UntrustableDestinationError(msg)
        record = DestinationTrustRecord(
            id=f"trust-{next(self._trust_ids)}",
            destinations=binding.canonical_destination_set,
            trust=DestinationTrust.USER_CHOSEN,
            established_at=self._destination_trust_now(),
        )
        await self.destination_trust.record(record)
        return self._checked(record, "establish_destination_trust")

    async def standing_destination_trust(self) -> tuple[DestinationTrustRecord, ...]:
        """List every destination-trust record that is live now (ADR-0242 §4).

        Read from :attr:`destination_trust` and from nothing else, so liveness is the
        store's — no surface and no test derives it from a recipient grant, a
        connection or a search that succeeded.
        """
        self.calls.append(("standing_destination_trust", {}))
        return self._checked(
            tuple(await self.destination_trust.live()), "standing_destination_trust"
        )

    async def revoke_destination_trust(self, record_id: DurableIdentifier) -> bool:
        """Withdraw one destination-trust record, or answer there was none (ADR-0242 §4).

        ``False`` where no live record carries the id, having written nothing, which
        is also the honest answer to a caller that lost a race to another revocation.
        """
        named = identifier(record_id, name="record_id")
        check_arguments(
            "revoke_destination_trust", max_bytes=self._max_payload_bytes, record_id=named
        )
        self.calls.append(("revoke_destination_trust", {"record_id": named}))
        if not any(held.id == named for held in await self.destination_trust.live()):
            return False
        await self.destination_trust.revoke(named, self._destination_trust_now())
        return True

    def _destination_trust_now(self) -> datetime:
        """The guarded reading of :attr:`destination_trust_clock` (ADR-0026 §2, §4).

        Raises:
            PlanningError: If the reading is not a conforming one.
        """
        try:
            return checked_clock(self.destination_trust_clock, owner="FakeAssistantEngine")()
        except ClockReadingError as exc:
            msg = (
                f"the fake engine's destination-trust clock returned a non-conforming "
                f"reading: {exc}"
            )
            raise PlanningError(msg) from exc

    async def _offerable_decision(self, decision_id: str) -> PermissionDecision:
        """Read the named decision and refuse it unless all seven conditions hold.

        In ADR-0235 §3's stated order, so the refusal is deterministic where more
        than one fails.

        Raises:
            UngrantableActError: If any condition fails.
        """
        confirmed = await self.trail.get(decision_id)
        if confirmed is None:
            msg = (
                f"the permission trail holds no decision {decision_id!r}, so there is no "
                f"recorded confirmation for an establishing act to ride (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if confirmed.ruling.outcome is not PermissionOutcome.CONFIRM:
            msg = (
                f"decision {decision_id!r} ruled {confirmed.ruling.outcome} and was never shown "
                f"as a question, so an answer to it establishes nothing (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if confirmed.step_id is not None or confirmed.execution_id is not None:
            msg = (
                f"decision {decision_id!r} belongs to a step of an execution, so a park holds "
                f"it and its answer rides resume rather than this operation (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        # **The whole trail and never a page** (ADR-0235 §3). This answer is what §3's
        # fourth condition is decided from, and a bounded scan would report a
        # confirmation whose answer has scrolled past the window as *offerable* — the
        # one refusal that would then arrive as the trail's `InvalidResolutionError`
        # instead of as this operation's own type. `grantable_decisions` above is a
        # page and is bounded by its `limit` with §3's window-completeness rule; this
        # is about one named decision and has no `limit` to widen.
        rows = await self.trail.export()
        resolution = next((row for row in rows if row.resolves == decision_id), None)
        if resolution is not None:
            msg = (
                f"decision {decision_id!r} was already answered by decision {resolution.id!r}; a "
                f"confirmation has one answer, so this one is spent (ADR-0044 §2b, ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        now = self._recipient_now()
        if confirmed.expires_at is not None and confirmed.expires_at <= now:
            msg = (
                f"decision {decision_id!r} stopped being answerable at "
                f"{confirmed.expires_at.isoformat()}, which is at or before {now.isoformat()} "
                f"(ADR-0059 §1, ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        binding = confirmed.egress_binding
        if not isinstance(binding, EgressBinding):
            msg = (
                f"decision {decision_id!r} records no egress call whose recipients could be "
                f"made standing (ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if binding.planned_with_external_content:
            msg = (
                f"decision {decision_id!r} records a call planned over external content; you "
                f"may approve such a call, and may not in that act make its recipients "
                f"standing (ADR-0193 §2, §4; ADR-0235 §3)"
            )
            raise UngrantableActError(msg)
        if self._park_excludes(decision_id):
            # ADR-0244 §5's **eighth** condition, named exactly as the seven are and
            # evaluated after them, so where more than one fails the first is the one
            # named and the refusal is deterministic across implementations.
            msg = (
                f"decision {decision_id!r} is the question a parked read holds, or has just "
                f"taken the answer to, so it is answered through resume rather than through "
                f"this operation (ADR-0244 §5)"
            )
            raise UngrantableActError(msg)
        return confirmed

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

    def hold(  # noqa: PLR0913 — a content, a kind, a band, an elision count and ADR-0189 §2's two origin facts; each is one thing a caller decides on its own
        self,
        record_id: str,
        *,
        content: str,
        kind: MemoryKind = MemoryKind.SEMANTIC,
        band: BeliefBand = BeliefBand.ASSERTED,
        evidence_elided: int = 0,
        attestation: Attestation | None = None,
        derived_from_external: bool = False,
        placement: Placement | None = None,
    ) -> Belief:
        """Put one belief in memory, and return it.

        The confidence is fixed and unadjusted: nothing here loses evidence, so
        there is no lost support for a presented value to have fallen with.

        ``evidence_elided`` is a knob because :func:`_summary_of` has to carry it
        (ADR-0107 §8 item 5) and a state no caller can script is a guarantee nobody
        can check. It is deliberately **not** derived from anything: it counts
        citations the belief no longer carries, on any band, and is independent of
        the confidence this fake fixes.

        **``attestation`` and ``derived_from_external`` are ADR-0189 §2's two facts,
        and only one of them is a knob** (#1523). The attestation is scripted, because
        a surface that names the reporting source and the instant it spoke cannot be
        tested without one. ``rests_on_recorded_external_content`` is **not**: ADR-0189
        §2 rules it "the value of
        :func:`~ai_assistant.core.types.rests_on_recorded_external_content` (ADR-0106
        §2) applied to the projected record's :class:`~ai_assistant.core.types.Provenance`",
        and that "no producer supplies it". So this builds the provenance the arguments
        describe and asks that function — the real projection's own derivation rather
        than a second spelling of it, which is what stops this fake representing a
        state no real projection can produce.

        **``Provenance``'s validator is doing work here rather than decorating.** It
        holds this fake to ADR-0092 §1's *if and only if*: an ``ATTESTED`` belief with
        no attestation, and an attestation on any other band, are both refused here
        exactly as the store refuses them — so the state ADR-0189 §2 declines to guard
        with a validator on :class:`~ai_assistant.core.types.Belief` is unscriptable
        anyway.

        ``derived_from_external`` is spelled as the ``Provenance`` field it is rather
        than as the answer it feeds, because it means nothing outside the ``DERIVED``
        band (ADR-0106 §2) and the band guard belongs to the predicate.

        Args:
            record_id: The belief's id.
            content: What the belief says.
            kind: Which of the four typed memories it is.
            band: The standing it is held with.
            evidence_elided: How many citations this record's history displaced.
            attestation: What reported it and when that source said so. Required on
                the ``ATTESTED`` band and refused on the other two.
            derived_from_external: Whether a ``DERIVED`` belief's warrant traces to
                recorded external content.
            placement: Who may receive this record (ADR-0217 §1). A knob because
                nothing on this surface writes one but the owner's own act: ADR-0204
                §2's derivation runs inside a turn and ADR-0217 §4's proposal is a
                producer's, so the two placements a consumer most needs to test an act
                against — a ``DERIVED`` narrowing and a model's ``PROPOSED`` one —
                cannot be reached by calling the fake. ``None`` leaves the record
                carrying §6's default, which is what a fresh belief has.

        Returns:
            The belief now held.
        """
        provenance = _provenance_for(
            band, attestation=attestation, derived_from_external=derived_from_external
        )
        held = Belief(
            id=record_id,
            band=band,
            kind=kind,
            content=content,
            confidence=1.0 if band is BeliefBand.ASSERTED else _CONFIDENCE,
            last_updated=_AT,
            evidence_elided=evidence_elided,
            attestation=provenance.attestation,
            rests_on_recorded_external_content=rests_on_recorded_external_content(provenance),
        )
        self.beliefs_held[record_id] = held
        # The placement follows the belief it belongs to, so seeding over an id this
        # engine already holds **replaces** it rather than inheriting the last one's.
        # A conditional write here would let `hold(id, placement=DERIVED)` followed by a
        # plain `hold(id)` leave a fresh, default-placed belief that `unguard` refuses —
        # a state no producer can reach and one the argument's own default denies.
        self.placements.pop(record_id, None)
        if placement is not None:
            self.placements[record_id] = placement
        self._spent.add(record_id)
        return held

    @staticmethod
    def retirement(
        record_id: str,
        *,
        content: str | None = None,
        band: BeliefBand = BeliefBand.ASSERTED,
        attestation: Attestation | None = None,
        derived_from_external: bool = False,
    ) -> Retirement:
        """Build one record a question's answer would retire (ADR-0189 §2).

        **The producer obligation is structural here rather than remembered.**
        ADR-0189 §2 rules that a producer sets ``warrant`` "**exactly when** it sets
        ``content``: both are resolved from one ``MemoryStore.get``, and ``None`` on
        both is the case ADR-0045 §6 produces" — and it deliberately puts *no*
        cross-field validator on :class:`~ai_assistant.core.types.Retirement`, for the
        ordering reason §2 gives. So nothing in ``core`` refuses the half-state, and
        this builder refuses it by construction instead: a ``content`` yields a whole
        warrant, no ``content`` yields none, and the two arms a surface must tell
        apart are the only two that can be scripted through it.

        A test that deliberately wants the half-state builds
        :class:`~ai_assistant.core.types.Retirement` directly — which is the honest
        division, since that state is off-contract rather than unrepresentable.

        The warrant's three facts come from one provenance for :meth:`hold`'s reason,
        and :class:`~ai_assistant.core.types.Warrant`'s own band-keyed validator then
        refuses every combination the band forecloses (ADR-0189 §3).

        Args:
            record_id: The retired record's id.
            content: What it says, or ``None`` where it no longer resolves.
            band: The standing it was held with.
            attestation: What reported it and when that source said so.
            derived_from_external: Whether a ``DERIVED`` record's warrant traces to
                recorded external content.

        Returns:
            The retirement, resolved with its whole warrant or tombstoned with none.
        """
        if content is None:
            return Retirement(record_id=record_id, content=None, warrant=None)
        provenance = _provenance_for(
            band, attestation=attestation, derived_from_external=derived_from_external
        )
        return Retirement(
            record_id=record_id,
            content=encodable_text(content),
            warrant=Warrant(
                band=band,
                rests_on_recorded_external_content=rests_on_recorded_external_content(provenance),
                attestation=provenance.attestation,
            ),
        )

    def _tick(self) -> datetime:
        """The next instant on this engine's logical clock.

        Strictly increasing rather than "one tick past whatever this conversation
        last had", which would let a continued conversation land *equal* to one
        started after it and leave the ordering to the tie-break.
        """
        return _AT + _TICK * next(self._ticks)

    def ask(  # noqa: PLR0913 — a content, a state, a band, ADR-0189 §2's two origin facts and what accepting would retire; each is one thing a caller decides on its own
        self,
        question_id: str,
        *,
        content: str,
        state: QuestionState,
        band: BeliefBand = BeliefBand.ASSERTED,
        attestation: Attestation | None = None,
        derived_from_external: bool = False,
        retires: Sequence[Retirement] = (),
    ) -> Question:
        """Put one deferred question in the queue, and return it.

        ``state`` decides which enumeration it lands in, and **only ``OPEN`` is
        answerable**. An ``INTERRUPTED`` question is a *second*, separate list all
        the way to the surface, because offering it beside the answerable ones would
        present a claim that cannot be taken (ADR-0078 §8); every terminal state —
        declined, applied, stale, re-deferred — appears in neither list and answers
        ``NOT_OPEN``, because those are questions the user has no move left on.

        **``band`` was fixed at ``ASSERTED`` and is now scriptable, because the band
        is what a surface renders the origin off** (#1523). ``attestation`` and
        ``derived_from_external`` describe the **proposal** — the record that would be
        written if the question were accepted — on the same reading ``band`` already
        has here, and describe no entry in ``retires`` (ADR-0189 §2). Each retirement
        answers for itself through its own :attr:`Retirement.warrant`, which is why
        they are built by :meth:`retirement` and passed in whole rather than derived
        from the question's own arguments: a question proposing the user's own
        assertion routinely retires an attested record, and a fake that borrowed one
        answer for the other would make that case unscriptable.

        Args:
            question_id: The question's id.
            content: What accepting would have the assistant believe.
            state: Where the question stands.
            band: The band the proposal **would** enter if accepted.
            attestation: What reported the proposal and when that source said so.
            derived_from_external: Whether a ``DERIVED`` proposal's warrant traces to
                recorded external content.
            retires: What accepting would retire, built by :meth:`retirement`.

        Returns:
            The question now queued.
        """
        provenance = _provenance_for(
            band, attestation=attestation, derived_from_external=derived_from_external
        )
        question = Question(
            id=question_id,
            state=state,
            content=content,
            kind=MemoryKind.SEMANTIC,
            band=band,
            rationale="the fake engine was told to ask",
            reason="the policy wants a human answer",
            retires=tuple(retires),
            asked_at=_AT,
            expires_at=None,
            attestation=provenance.attestation,
            rests_on_recorded_external_content=rests_on_recorded_external_content(provenance),
        )
        self._spent.update(retirement.record_id for retirement in question.retires)
        match state:
            case QuestionState.OPEN:
                self.questions_open[question_id] = question
            case QuestionState.INTERRUPTED:
                self.questions_interrupted[question_id] = question
            case _:
                self.questions_settled[question_id] = question
        return question

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
        scope: Sequence[GrantScope] = (GrantScope.FACET,),
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

    def park_read(
        self,
        handle: str,
        *,
        query: str,
        origin: str = "search.example",
        egress: EgressBinding | None = None,
        authorization: AuthorizationProjection | None = None,
    ) -> Confirmation:
        """Park one **read** this engine will answer, and return its question (§4, §5).

        A lever, because a park is reached inside a turn, so an implementation has to
        be handed to a suite that drives one — and a surface lane needs a question to
        render without a search account, a policy and a trail behind it.

        **``parameters`` carry the exact query**, because ADR-0244 §13 makes that what a
        surface renders and forbids a summary, an abbreviation, a truncation, a re-cased
        form or a paraphrase of it. A fake whose question carried a placeholder would
        certify a surface that renders one.

        **``read`` is** :attr:`~ai_assistant.core.types.ReadKind.WEB_SEARCH`, which is
        the one kind ADR-0244 parks; §20 defers the rest by name.

        Args:
            handle: The continuation handle this park is answered by.
            query: The composed query, byte for byte as a ruling was taken over it.
            origin: The origin the request names.
            egress: The binding the ruling was taken over, reduced here by the rule
                the real engine uses (ADR-0178 §5). ``None`` builds a question with no egress
                member, which ADR-0244 §4 says a real ``WEB_SEARCH`` park never has —
                and which a surface must still not crash on.
            authorization: What answering would establish (ADR-0254 §11), or
                ``None`` where answering proposes no row.

        Returns:
            The parked read's confirmation.
        """
        confirmation = Confirmation(
            tool_id="web_search",
            tool_description="asks one connected search account a question",
            parameters={"origin": origin, "query": query},
            reason="this lookup would leave the device, so it is put to you as a question",
            token=ContinuationToken(handle=handle),
            egress=(
                None
                if egress is None
                else ConfirmationEgress(
                    account_identity=egress.account.identity,
                    spans=egress.spans,
                    planned_with_external_content=egress.planned_with_external_content,
                    coverage=egress.coverage,
                )
            ),
            read=ReadKind.WEB_SEARCH,
            # ADR-0254 §11, absent unless the caller states one.
            authorization=authorization,
        )
        self.read_parked[handle] = confirmation
        return confirmation

    def _park_excludes(self, decision_id: str) -> bool:
        """Whether ADR-0244 §5's eighth condition excludes ``decision_id``.

        **Stated over three dispositions and not over an open park**, which is §5's own
        clause and the property it exists to have: a park that settles ``APPROVED`` or
        ``DENIED`` holds a resolution the answering call has not yet recorded, so a
        decision that left the listing at the settlement would be one the establishing
        act could resolve **first** — recording an ``ALLOW`` the user never gave that
        answer for.

        A ``CANCELLED`` park's decision returns to the listing, because a cancellation
        writes no resolution and never will; an ``EXPIRED`` one's stays out, refused by
        ADR-0235 §3's **fifth** condition on the shared deadline rather than by this one.
        This fake models the first two members it can reach — a question still open, and
        one an answer took — and a cancellation removes the exclusion by removing the
        decision from :attr:`_read_decisions`.

        Args:
            decision_id: The recorded ``CONFIRM`` under test.

        Returns:
            Whether a read park this engine holds excludes it.
        """
        return decision_id in self._read_decisions.values()

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


def _approving(confirmed: PermissionDecision) -> PermissionRuling:
    """The resolving ``ALLOW`` an approving answer to ``confirmed`` produces.

    **``authorised_by`` names the confirmation and is not optional here**:
    ``AuditTrail.record`` refuses a resolving ``ALLOW`` that does not rest on the
    question it answers, so a ruling without it is one no conforming trail accepts
    (ADR-0193 §6's route-(a) discriminator). Shipping policies author it —
    ``ActionPolicy.resolve``'s own obligation — and this fake authors no ruling
    anywhere else, so the one place it stands in for a policy is stated once rather
    than twice.

    Args:
        confirmed: The recorded ``CONFIRM`` being answered.

    Returns:
        The ruling, resting on that confirmation.
    """
    return PermissionRuling(
        outcome=PermissionOutcome.ALLOW,
        reason="the fake engine records the answer the user gave",
        authorised_by=confirmed.id,
    )


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


def _provenance_for(
    band: BeliefBand,
    *,
    attestation: Attestation | None,
    derived_from_external: bool,
) -> Provenance:
    """The provenance a belief in this band, with these facts, would have been stored with.

    **Built so that one function answers ADR-0189 §2's predicate here and in the real
    engine.** §2 rules ``rests_on_recorded_external_content`` to be
    :func:`~ai_assistant.core.types.rests_on_recorded_external_content` applied to the
    projected record's ``Provenance``, and that "no producer supplies it, no surface
    recomputes it from ``band``". A fake that mapped band to answer directly would be
    the second spelling ADR-0106 §2 exists to make unwritable — so this reconstructs
    the input that function takes and lets it decide.

    The band is inverted to a :class:`~ai_assistant.core.types.MemorySource` rather
    than carried, because ``Provenance`` is keyed on the source and ``band_of`` is the
    projection (ADR-0072 §4). ``DERIVED`` has two pre-images and ``INFERRED`` is the
    one chosen: ``OBSERVED`` reaches the same band and the same predicate, so nothing
    downstream can tell them apart, and picking the other would change no answer.

    Args:
        band: The standing the record is held with.
        attestation: What reported it, where the band is ``ATTESTED``.
        derived_from_external: Whether a ``DERIVED`` warrant traces to recorded
            external content.

    Returns:
        A provenance carrying exactly those facts.

    Raises:
        ValidationError: Where the band and the attestation disagree — ADR-0092 §1's
            *if and only if*, enforced by ``Provenance`` itself rather than restated
            here.
    """
    match band:
        case BeliefBand.ASSERTED:
            source = MemorySource.USER_ASSERTED
        case BeliefBand.DERIVED:
            source = MemorySource.INFERRED
        case BeliefBand.ATTESTED:
            source = MemorySource.EXTERNAL
        case _:  # pragma: no cover - exhaustive
            assert_never(band)
    return Provenance(
        source=source,
        confidence=1.0 if band is BeliefBand.ASSERTED else _CONFIDENCE,
        last_updated=_AT,
        attestation=attestation,
        derived_from_external=derived_from_external,
    )


def _summary_of(belief: Belief) -> BeliefSummary:
    """Project one held belief into the listing's summary (ADR-0085 §4a).

    ``evidence_elided`` is carried through as held, on every band, so the fake and
    the real projection agree about it (ADR-0107 §8 item 5). A fake that dropped it
    would let a conformance suite pass against a listing that discloses less than
    the detail view it was drilled into.

    **ADR-0189 §2's two fields are carried for exactly that argument, one field over**
    (#1523). ADR-0107 §3 refused both "put the field on ``BeliefSummary`` only" and
    "put it on ``Belief`` only" and required both DTOs to carry it under one name,
    because "a listing row that answered less than the row it links to is the same
    projection defective in one place" — and a fake that dropped the attestation here
    would let a listing render the generic attested line while every single-belief
    test passed, which is #1517's second finding exactly.
    """
    return BeliefSummary(
        id=belief.id,
        band=belief.band,
        kind=belief.kind,
        content=belief.content,
        confidence=belief.confidence,
        last_updated=belief.last_updated,
        evidence_count=belief.evidence_count,
        lost_evidence=belief.lost_evidence,
        valid_until=belief.valid_until,
        evidence_elided=belief.evidence_elided,
        attestation=belief.attestation,
        rests_on_recorded_external_content=belief.rests_on_recorded_external_content,
    )


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


def _turn(utterance: str) -> TurnResult:
    """A turn whose plan has no step — a real ratified shape, not a stub.

    ``utterance`` is stripped **once** here and that one string reaches both
    :attr:`TurnResult.utterance` and the brief's ``outcome``, which is the shape of the
    production path (ADR-0248 §1, ADR-0249 §3): a goal opened by this system carries
    revision 1 whose outcome *is* the request. So this fake exhibits the byte-equality
    ADR-0248 §6 asserts rather than two normalisations that happen to agree — and a fake
    that let the two diverge would certify a consumer the real engine never produces.

    The turn carries the **brief** and not the record (ADR-0249 §11), because that is
    what a ``TurnResult`` holds: the projection goes over the wire and the record stays
    inside ``orchestration``.
    """
    request = utterance.strip()
    goal = Goal(
        id="g-1",
        conversation_id="c-1",
        interpretation=(
            GoalInterpretation(
                revision=1,
                outcome=request,
                outcome_ground=Ground.USER_STATED,
                outcome_span=request,
                recorded_at=_AT,
                raised_by="t-1",
            ),
        ),
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
        last_engaged_at=_AT,
    )
    return TurnResult(
        utterance=request,
        goal=GoalBrief.of(goal),
        context=CurrentContext(
            now=_AT,
            time_of_day=TimeOfDay.AFTERNOON,
            is_weekend=False,
            within_working_hours=True,
        ),
        memories=(),
        plan=ActionPlan(
            id="p-1", goal_id=goal.id, steps=(), created_at=_AT, targets_revision=goal.revision
        ),
    )


__all__ = ["FakeAssistantEngine"]

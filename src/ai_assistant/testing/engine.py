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

import hashlib
import re
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Final, assert_never, cast

from ai_assistant.core.clock import ClockReadingError, checked_clock
from ai_assistant.core.errors import (
    GrantError,
    InvalidGrantError,
    InvalidRecipientGrantError,
    NotificationBudgetError,
    OversizedValueError,
    PlanningError,
    UngrantableActError,
    UngrantableSourceError,
    UnknownContinuationError,
    UnknownConversationError,
)
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    ActionPlan,
    AnswerKind,
    AnswerOutcome,
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    Confirmation,
    ConfirmationEgress,
    ContinuationToken,
    ConversationDigest,
    ConversationSummary,
    CurrentContext,
    Disposition,
    EgressBinding,
    ExecutionState,
    Goal,
    GrantableSource,
    GrantScope,
    IngestSummary,
    LearnDecision,
    LearnOutcome,
    MemoryKind,
    MemorySource,
    NotificationDelivery,
    ObservationReport,
    OperationConfirmation,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Placement,
    PlacementReach,
    PlacementSetter,
    Provenance,
    Question,
    QuestionState,
    RecipientGrant,
    RecipientGrantNotEstablished,
    RecipientGrantOutcome,
    RecordedInvocation,
    ReplyChunk,
    Retirement,
    RoutableOperation,
    RoutedOperation,
    RouteOutcome,
    SkipReason,
    SourceGrant,
    SpendTotal,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
    SpokenRendering,
    SpokenTurn,
    StepExecution,
    StepOutcome,
    StepStatus,
    TimeOfDay,
    TurnOutcome,
    TurnResult,
    Warrant,
    describe_untrusted,
    encodable_text,
    is_live_confirmation_park,
    rests_on_recorded_external_content,
    secret_value,
)

# ADR-0206 §3's placement is **named rather than copied**, exactly as ADR-0207 §5's
# third arm requires of `SPOKEN_PARK_SENTENCE` below and ADR-0087 §7 requires of the
# payload encoder above: "the canonical fake reaches for this one rather than growing
# a second copy to keep in step by hand". A re-declared triple here would be a second
# disclosure rule that drifts silently — the fake would certify a consumer against a
# hub that speaks a different set of notifications, which is the one thing this
# package may not do, and is the drift golden rule 1 exists to prevent rather than an
# instance of it. `lint-imports` holds the boundary that rule is enforced by, and
# `ai_assistant.testing` is test-only rather than a runtime subsystem.
from ai_assistant.orchestration.disclosure import notification_is_speakable
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
    record_the_grant,
    rides_an_establishing_act,
)
from ai_assistant.orchestration.speech import SPOKEN_PARK_SENTENCE
from ai_assistant.testing.archive import FakeTranscriptArchive
from ai_assistant.testing.connections import FakeConnectionProvisioner
from ai_assistant.testing.notifications import (
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
)
from ai_assistant.testing.permissions import FakeAuditTrail
from ai_assistant.testing.reads import FakeSourceReadTrail
from ai_assistant.testing.recipient_grants import FakeRecipientGrantStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from ai_assistant.core.protocols import AuditTrail, SourceReadTrail, SpendLedger
    from ai_assistant.core.types import (
        ConnectedAccount,
        ConnectionAct,
        DurableIdentifier,
        EncodableText,
        FeedbackEvent,
        HeldNotification,
        Identifier,
        NonBlankEncodableText,
        NotificationPreferences,
        RoutedListing,
        SecretValue,
        SourceReadRecord,
        TranscriptArchiveSize,
        TranscriptEntry,
        TranscriptHit,
        UtcInstant,
    )

#: A fixed instant, so a fake engine's output is deterministic without a clock.
_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: How far each activity stamp advances per event. A logical clock rather than a
#: real one: it keeps the ordering deterministic and keeps the fake free of a wall
#: clock.
_TICK = timedelta(seconds=1)

#: Where :func:`_pieces_of` cuts a composed answer: immediately before each word
#: that follows whitespace. Zero-width, so the pieces concatenate back to the answer
#: byte for byte — which is the property ADR-0173 §3 makes load-bearing.
_BEFORE_A_WORD: Final = re.compile(r"(?<=\s)(?=\S)")

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


@dataclass(frozen=True, slots=True)
class _Settled:
    """What one answered continuation token still names (ADR-0198 §1).

    The fake's counterpart to the engine's own settled record, and it retains the
    same three immutable facts and no fourth: the disposition the resolution
    reached, the binding's ``step_id``, and the ``tool_id`` the step bound. The
    execution **state** is deliberately absent — §2 rules it re-read at the moment
    of the restatement rather than snapshotted at settlement, so it is held in
    :attr:`FakeAssistantEngine.executions`, which stands in for a plan store and
    which a test can empty to reach §2's store-no-longer-holds-it case.
    """

    execution_id: str
    step_id: str
    tool_id: str | None
    disposition: Disposition


#: The answer a routed pass this fake resolved carries. Fixed rather than composed,
#: because a fake originates no model call — and present rather than ``None`` because
#: ADR-0197 §8 makes a routed pass that is not a park owe one.
_ROUTED_REPLY: Final = "the assistant did what you asked."


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
        turn_outcome: What :meth:`converse` returns. Defaults to a turn whose plan
            had no step — a real ratified shape, not a stub.
        observation: What :meth:`observe` returns.
        answered: What :meth:`answer` returns, or ``None`` to synthesise one from
            the question's own state.
    """

    def __init__(
        self,
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        max_outstanding_confirmations: int = _DEFAULT_MAX_OUTSTANDING,
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
            max_outstanding_confirmations: The ceiling ADR-0198 §4 reuses as the
                bound on :attr:`settled`. This fake parks by a lever rather than by
                admitting a turn, so the ceiling's *backpressure* half has nothing
                here to bind; what it does bind is the retention, which is the half
                a conformance case can reach. A subject built at one is how §4's
                discard is made cheap to observe. Guarded exactly as the concrete
                engine guards it, **classification included**: ADR-0084 §4's
                substitutability runs in both directions, so a fake that admitted a
                deployment no engine admits would let a consumer's tests pass over a
                configuration production cannot be built into — and a fake that
                refused the same value with a different class would make the two
                disagree about what kind of failure it is. Unrefused, the value
                surfaces later and as something else: ``1.5`` would bound the
                retention at two, and ``0`` would discard from an empty table on the
                first settlement.

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
        self._max_outstanding = max_outstanding_confirmations
        #: The notification surface's whole state, public so a consumer can
        #: seed it: ``await engine.notification_store.admit(candidate,
        #: policy=engine.notification_policy)`` is how a held record gets
        #: here, there being no producer on this surface (ADR-0130 §1).
        self.notification_store = FakeNotificationStore()
        self.notification_policy = FakeNotificationPolicy()
        self.beliefs_held: dict[str, Belief] = {}
        #: The transcript archive this engine's seven archive operations read and
        #: destroy against (ADR-0225 §10), public so a consumer can seed it —
        #: ``engine.archive.hold(entry)`` — there being no producer on this
        #: surface. It is the **wide** seam, which carries no ``append``: writing
        #: is capture's, and a fake engine that could write would give away the
        #: split §10 buys.
        self.archive = FakeTranscriptArchive()
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
        #: The routed parks this engine will resolve, by continuation handle
        #: (ADR-0197 §7). Deliberately a **second** table beside ``parked``: a routed
        #: park and a tool park are answered through one method and one token space,
        #: and what tells them apart is which table the handle is in — which is the
        #: arrangement the real engine has, so a consumer's test cannot pass here on a
        #: shape no implementation may take.
        self.routed_parked: dict[str, OperationConfirmation] = {}
        self.questions_open: dict[str, Question] = {}
        self.questions_interrupted: dict[str, Question] = {}
        #: Questions in a terminal state — declined, applied, stale, re-deferred.
        #: Neither enumeration shows one and :meth:`answer` refuses it, because
        #: "that question is not open" is what the surface has to say about it.
        self.questions_settled: dict[str, Question] = {}
        self.conversations_held: dict[str, ConversationDigest] = {}
        #: When each conversation was last active — set at creation and refreshed
        #: whenever a turn begins against it (ADR-0074 §2). Held beside the digests
        #: rather than on them because a
        #: :class:`~ai_assistant.core.types.ConversationDigest` is the deletion
        #: ceremony's shape and carries no activity stamp.
        self.activity: dict[str, datetime] = {}
        #: What :meth:`converse_spoken` reports having heard (ADR-0200 §4). A
        #: **blank** value — empty or whitespace only — is what makes that call take
        #: §4's no-words shape, which is the one shape a consumer cannot reach by
        #: scripting :attr:`turn_outcome`.
        self.spoken_transcript: str = "What did I do last week?"
        #: What this engine's synthesizer can produce (ADR-0200 §3). The call
        #: renders in the **first** member of ``plays`` this set also names; an
        #: empty intersection degrades the turn, which is how a consumer reaches
        #: that shape without a seam of its own.
        self.spoken_formats: frozenset[SpokenAudioFormat] = frozenset(SpokenAudioFormat)
        #: What a device has reported playing, by the episode id
        #: :meth:`converse_spoken` disclosed for that turn (ADR-0205 §3). Written
        #: **once** per turn: a second report naming a turn already in here performs
        #: nothing, and a report naming an episode this engine never disclosed is
        #: discarded — which is §1's rule, kept here so a consumer can drive the page
        #: against it without a store.
        self.deliveries: dict[str, SpokenDelivery] = {}
        #: How many turns :meth:`converse_spoken` has recorded per conversation, so
        #: that each one's episode id is distinct and in ADR-0074 §3's reserved
        #: ``conv:`` namespace. A counter rather than the length of anything, for
        #: :attr:`_written`'s reason one field over.
        self._spoken_turns: dict[str, int] = {}
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
        self.parked: dict[str, Confirmation] = {}
        #: The bindings this engine has **answered** and still retains, by handle and
        #: oldest settlement first (ADR-0198 §1, §4). A third table beside ``parked``
        #: and ``routed_parked`` for their reason: which table a handle is in is what
        #: decides what a ``resume`` presenting it gets, and a settled record is not a
        #: park — it holds no live turn, authorises nothing, and is never enumerated
        #: by ``pending_confirmations``. Bounded by
        #: ``max_outstanding_confirmations``, discarding the least recently settled.
        self.settled: dict[str, _Settled] = {}
        #: The execution state each settled binding names, standing in for the plan
        #: store a restatement re-reads (ADR-0198 §2). Public and mutable because
        #: §2's other clause — where the store no longer holds the execution, the
        #: restatement raises ``PlanningError`` and asserts nothing — is reachable
        #: only by taking one out, and no call on this surface removes one.
        self.executions: dict[str, ExecutionState] = {}
        self.turn_outcome: TurnOutcome | None = None
        self.observation: ObservationReport = ObservationReport()
        self.answered: AnswerOutcome | None = None
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

    # --- the two turn calls -----------------------------------------------

    def _resolve(self, conversation_id: str | None) -> str:
        """Continue the conversation named, or start one where none was (ADR-0074 §1).

        **An id this engine does not know is refused, not silently started.**
        Silently starting one turns a typo or a stale copy-paste into "my
        conversation vanished" and lands the user's continuation somewhere they
        cannot find — and a fake that started one instead would let a client's tests
        pass over the exact path the real engine refuses.
        """
        if conversation_id is None:
            return self.start_conversation(f"c-{len(self.conversations_held) + 1}")
        if conversation_id not in self.conversations_held:
            msg = f"no conversation {conversation_id!r}"
            raise UnknownConversationError(msg)
        self.activity[conversation_id] = self._tick()
        return conversation_id

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Run one turn against a conversation, minting one if none is named."""
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments(
            "converse",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            timeout=timeout,
            conversation_id=selected,
        )
        self.calls.append(("converse", {"utterance": utterance, "conversation_id": selected}))
        held = self._resolve(selected)
        # ``reply`` is populated because ADR-0170 §4 obliges an answer on every shape
        # but a park and a recovered resume, and ``TurnOutcome`` refuses an outcome
        # that owes one and carries none. A fake that returned ``None`` here would
        # let a client's tests pass over a shape the type does not admit.
        outcome = self.turn_outcome or TurnOutcome(
            turn=_turn(utterance),
            conversation_id=held,
            reply=f"This fake engine composed no real answer to {utterance.strip()!r}.",
        )
        return self._checked(outcome, "converse")

    def converse_streaming(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # the caller's budget, as the Protocol declares it
        conversation_id: Identifier | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Run one turn, publishing its answer as chunks first (ADR-0173 §4).

        **The chunks are derived from the outcome rather than scripted beside it**,
        which is what keeps the fake honest about the one property ADR-0173 §3 makes
        load-bearing: ``reply`` is the join of what was yielded, so a client tested
        against this double can never pass over a disagreement the real engine
        cannot produce. Script :attr:`turn_outcome` and the split follows.

        The local refusals are raised **from the call**, as the concrete engine
        raises them and as ``StreamingCompleter.stream`` raises its own, so a caller
        that never iterates still sees them. Everything else — an unknown
        conversation included — arrives from the iteration.
        """
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments(
            "converse_streaming",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            timeout=timeout,
            conversation_id=selected,
        )
        return self._streamed(utterance, conversation_id=selected)

    async def _streamed(
        self, utterance: EncodableText, *, conversation_id: str | None
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Yield the outcome's own reply in pieces, then the outcome."""
        self.calls.append(
            ("converse_streaming", {"utterance": utterance, "conversation_id": conversation_id})
        )
        held = self._resolve(conversation_id)
        outcome = self.turn_outcome or TurnOutcome(
            turn=_turn(utterance),
            conversation_id=held,
            reply=f"This fake engine composed no real answer to {utterance.strip()!r}.",
        )
        checked = self._checked(outcome, "converse_streaming")
        for piece in _pieces_of(checked.reply):
            yield self._checked(ReplyChunk(text=piece), "converse_streaming")
        yield checked

    async def converse_spoken(
        self,
        utterance: SpokenAudio,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
        conversation_id: Identifier | None = None,
        delivery: SpokenDeliveryReport | None = None,
    ) -> SpokenTurn:
        """Run one spoken turn, scripted by :attr:`spoken_transcript` (ADR-0200 §3).

        **The transcript is the lever, and everything else follows from it**, which
        keeps this double honest about the join ADR-0200 §4 makes load-bearing: a
        blank transcript yields §4's no-words shape — four members, no turn, no
        conversation and no exception — and a non-blank one reaches ``heard``
        **byte for byte**, leading and trailing spaces included. A consumer that
        wants the turn to say something else scripts :attr:`turn_outcome` as it
        does for :meth:`converse`.

        The rendering is the first member of ``plays`` that :attr:`spoken_formats`
        also names, and its octets are a hash of what was said — deterministic,
        opaque, and not to be decoded by anything. An empty intersection degrades
        exactly as ADR-0200 §4 rules: ``spoken`` ``None``, ``spoken_degraded``
        ``True``, and no rendering attempted.

        **A scripted turn that parks says ADR-0207 §2's sentence** rather than
        falling silent, on both of §1's shapes — a ``turn_outcome`` whose step reached
        ``AWAITING_CONFIRMATION`` and one whose routed operation did — by the same rule
        and under the same ladder as an answer, so this double satisfies the widened
        validator rather than being exempted from it. The sentence is the
        ``orchestration`` constant itself, imported and never re-declared (ADR-0207
        §5): a copied literal here would be exactly the drift golden rule 1 exists to
        prevent, arriving through the package whose job is to make the contract
        testable. Every other ``reply``-less outcome — a composition failure, a
        recovered resume — is silent as before (§3).

        Args:
            utterance: The recording. Carried no further than this call — nothing
                here writes it, logs it or keeps it (ADR-0200 §8), and the fake
                never decodes it, because what it *says* is not something a
                transcriber's caller may infer from its bytes.
            plays: What the caller can render, in preference order.
            timeout: The budget for the whole call.
            conversation_id: The conversation to continue, or ``None``.
            delivery: What a device played of an earlier turn, naming that turn by
                the ``episode_id`` this method disclosed for it (ADR-0205 §1). It is
                applied **before** anything else this call does, so a recording that
                carried no words still records it; a report naming an episode this
                engine never disclosed, or one whose turn is already stamped, is
                discarded and the call proceeds as though none had been given.

        Returns:
            The transcript, the turn it drove, the rendering of the answer, and the
            id of the episode recording it.

        Raises:
            ValueError: If ``plays`` is empty, ``conversation_id`` is blank, a
                ``delivery`` was supplied beside a ``conversation_id`` of ``None``,
                or a supplied ``delivery`` carries a state of ``UNKNOWN`` — each
                refused locally, before anything else, and before there is any
                transcript to be blank (ADR-0200 §4, ADR-0205 §1, §2).
            UnknownConversationError: If ``conversation_id`` names no conversation
                this engine holds — where a turn actually ran, and also where a
                ``delivery`` was supplied, since the report is recorded against that
                conversation before the recording is looked at.
        """
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        if not plays:
            msg = "plays must name at least one format the caller can render (ADR-0200 §3)"
            raise ValueError(msg)
        _refuse_unusable_report(delivery, conversation_id=selected)
        check_arguments(
            "converse_spoken",
            max_bytes=self._max_payload_bytes,
            utterance=utterance,
            plays=plays,
            timeout=timeout,
            conversation_id=selected,
            delivery=delivery,
        )
        self.calls.append(
            (
                "converse_spoken",
                {"plays": plays, "conversation_id": selected, "delivery": delivery},
            )
        )
        if delivery is not None:
            # ADR-0205 §1: recorded **before the turn plans**, so a blank recording,
            # a degradation or a failure later in the call does not lose a fact about
            # a turn that has already happened. `selected` is not None here, which is
            # what the refusal above guarantees.
            self._record_delivery(str(selected), delivery)
        heard = self.spoken_transcript
        if not heard.strip():
            return self._checked(SpokenTurn(), "converse_spoken")
        held = self._resolve(selected)
        outcome = self.turn_outcome or TurnOutcome(
            turn=_turn(heard),
            conversation_id=held,
            reply=f"This fake engine composed no real answer to {heard.strip()!r}.",
        )
        chosen = next((member for member in plays if member in self.spoken_formats), None)
        # ADR-0205 §4: every turn of this operation is stamped `UNKNOWN` at capture,
        # the park and the degraded synthesis included, so the id is minted before
        # the rendering is decided and reaches every shape below that recorded one.
        episode = self._spoken_episode(held)
        # ADR-0207 §1: a live confirmation park speaks §2's sentence rather than
        # falling silent, and the constant is **named** rather than copied (§5's
        # third arm), so this double cannot drift from the engine it stands in for.
        # Every other `reply`-less shape keeps ADR-0200 §4's silence (§3).
        text = outcome.reply
        if text is None and is_live_confirmation_park(outcome):
            text = SPOKEN_PARK_SENTENCE
        if text is None:
            return self._checked(
                SpokenTurn(heard=heard, outcome=outcome, episode_id=episode), "converse_spoken"
            )
        if chosen is None:
            return self._checked(
                SpokenTurn(heard=heard, outcome=outcome, spoken_degraded=True, episode_id=episode),
                "converse_spoken",
            )
        rendering = SpokenAudio(content=_pseudo_audio(text, chosen), media_type=chosen)
        return self._checked(
            SpokenTurn(heard=heard, outcome=outcome, spoken=rendering, episode_id=episode),
            "converse_spoken",
        )

    def _spoken_episode(self, conversation_id: str) -> str:
        """Mint this turn's episode id, in ADR-0074 §3's reserved namespace.

        Derived from the conversation and a per-conversation counter, exactly as a
        ``ConversationStore`` derives one from the conversation and the ordinal it
        allocated — so two turns cannot collide and a consumer can hand the value
        back on the next call, which is the whole of what ADR-0205 §1 discloses it
        for. Recorded as ``UNKNOWN`` at once (§4).
        """
        ordinal = self._spoken_turns.get(conversation_id, 0) + 1
        self._spoken_turns[conversation_id] = ordinal
        episode = f"conv:{conversation_id}:{ordinal}"
        self.deliveries[episode] = SpokenDelivery(state=SpokenDeliveryState.UNKNOWN)
        return episode

    def _record_delivery(self, conversation_id: str, report: SpokenDeliveryReport) -> None:
        """Stamp the turn the report names, if it is this conversation's and unstamped.

        ADR-0205 §3's three conditions, over what this double holds instead of an
        index: the episode belongs to the conversation named, it is one this engine
        disclosed, and its recorded delivery is still ``UNKNOWN``. Any of them
        failing performs nothing and raises nothing.

        Raises:
            UnknownConversationError: If the conversation is not one this engine
                holds — the refusal ``ConversationStore.record_delivery`` carries.
        """
        if conversation_id not in self.conversations_held:
            msg = f"no conversation {conversation_id!r}"
            raise UnknownConversationError(msg)
        recorded = self.deliveries.get(report.episode_id)
        if recorded is None or recorded.state is not SpokenDeliveryState.UNKNOWN:
            return
        if not report.episode_id.startswith(f"conv:{conversation_id}:"):
            return
        self.deliveries[report.episode_id] = report.delivery

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, as the Protocol declares it
        remember_recipients_until: UtcInstant | None = None,
    ) -> TurnOutcome:
        """Answer a parked confirmation, restate an answer already given, or refuse.

        **Two kinds of park, one method and one token space** (ADR-0197 §7). A handle in
        :attr:`routed_parked` answers a routed operation and its outcome carries ``step``
        ``None`` and ``routed`` non-``None``; every other handle answers a parked step and
        is ruled exactly as it was before ADR-0197. A token in neither is unresolvable and
        yields ``UnknownContinuationError`` and never a denial (ADR-0084 §7).

        **A handle in :attr:`settled` is answered rather than refused** (ADR-0198 §§1-3).
        Resolving a parked step retains its binding under the handle, and a later
        ``resume`` presenting that token **restates** the recorded answer: it returns an
        outcome describing the settled binding and raises nothing. The restatement is
        returned **whatever ``approved`` carries** and the recorded answer stands
        unchanged, because a park is answered once (ADR-0044 §2b) and a second answer is
        never honourable whatever it says. It performs nothing: no tool, no ruling, no
        composed reply, no captured episode.

        **A routed park is not retained** (§6), which is why the routed branch runs first
        and is unchanged: it is claimed once and atomically, and a second presentation of
        its token still falls through to the refusal below.
        """
        # Validated locally and before any I/O, exactly as the concrete engine
        # validates it (ADR-0085 §9): ``UtcInstant`` is a pydantic annotation, so an
        # in-process caller is not checked against it by anything else, and a fake
        # that let a naive instant through would certify a consumer against a hub
        # that refuses it.
        until = (
            None
            if remember_recipients_until is None
            else utc_instant(remember_recipients_until, name="remember_recipients_until")
        )
        check_arguments(
            "resume",
            max_bytes=self._max_payload_bytes,
            token=token,
            approved=approved,
            timeout=timeout,
            remember_recipients_until=until,
        )
        self.calls.append(("resume", {"token": token.handle, "approved": approved}))
        if token.handle in self.routed_parked:
            if remember_recipients_until is not None and approved:
                # A routed park records no ``PermissionDecision`` and carries no
                # egress binding, so there is nothing for a grant to be transcribed
                # from (ADR-0235 §2). Refused **before** the park is claimed, so the
                # operation may still be asked for again.
                msg = (
                    "this token names a routed operation rather than a confirmation about "
                    "an outbound call, so answering it establishes no standing recipient "
                    "grant; nothing was claimed (ADR-0235 §2)"
                )
                raise UngrantableActError(msg)
            return await self._resume_routed(token.handle, approved=approved)
        if token.handle not in self.parked:
            # **A restatement establishes nothing and consults the argument no more
            # than it consults ``approved``** (ADR-0198 §§1-3, ADR-0235 §4): it drives
            # nothing, so its outcome carries ``recipient_grant`` ``None``.
            return self._restate(token.handle)
        # **The act's two refusals fire before anything is answered** (ADR-0235 §1,
        # §2), so the park survives them and the same token answers it again without
        # the argument.
        establishing_at: datetime | None = None
        answered: PermissionDecision | None = None
        if until is not None:
            if approved:
                self._check_establishable(token.handle)
                establishing_at = self._establishing_instant(until)
            # **The answer is recorded on both answers, and before the park is
            # evicted.** ADR-0235 §2 supplies the argument beside ``approved=False``
            # and rules that "the answer is recorded as a ``DENY`` exactly as it is
            # today" — ADR-0042 §4's guarantee, which
            # :attr:`RecipientGrantNotEstablished.DECLINED` then *asserts* on the
            # carrier. A fake that carried ``DECLINED`` over an empty trail would be
            # claiming an auditable settled decision it never made.
            #
            # And before the eviction, which is the order the concrete engine has
            # and the one ADR-0193 §2 fixes: the runner records the resolving
            # decision and only then does the engine replace the park with its
            # settled record. A fake that settled first would, on a trail that
            # refused the write, leave a token restating an execution no answer
            # authorised — a state no conforming hub can be in, and the one a
            # consumer's own retry logic would be written against.
            #
            # A park no confirmation is bound to (:meth:`hold_confirmation_decision`)
            # has no recorded ``CONFIRM`` for an answer to resolve, so there is
            # nothing to author rather than a write this drops.
            if token.handle in self._parked_decisions:
                answered = await self._record_the_answer(
                    token.handle,
                    at=establishing_at if establishing_at is not None else self._recipient_now(),
                    approved=approved,
                )
        confirmation = self.parked.pop(token.handle)
        # **The reference names the decision that actually cleared the step**, where
        # this path recorded one (ADR-0004 §7, ADR-0014 §4). Before ADR-0235 nothing
        # on this fake's resume recorded a decision at all, so the reference resolved
        # to nothing on every path and could mislead nobody; now that the
        # establishing act records one, a reference naming a *different* id would be
        # the dangling ``approval_ref`` ADR-0014 §4 exists to prevent, in the one
        # state a consumer can actually resolve.
        cleared_by = (
            (f"decision-{token.handle}" if answered is None else answered.id) if approved else None
        )
        # **A denial is a result, not an exception** (ADR-0042 §4): the adapter
        # conveys consent, the policy rules on it, and the engine records and
        # executes. Only ``approved=False -> DENY`` is guaranteed; ``approved=True``
        # may still be refused. Raising here instead would give a client a failure
        # path the in-process engine does not have.
        resolved = StepOutcome(
            disposition=Disposition.EXECUTED if approved else Disposition.DENIED,
            state=ExecutionState(
                id=f"exec-{token.handle}",
                plan_id=f"plan-{token.handle}",
                steps=(
                    StepExecution(
                        step_id="step-1",
                        # A succeeded step names the decision that cleared it, and a
                        # denied one names why it was skipped: the type refuses a
                        # step that claims either without saying so (ADR-0004 §7).
                        status=StepStatus.SUCCEEDED if approved else StepStatus.SKIPPED,
                        attempts=1 if approved else 0,
                        approval_ref=cleared_by,
                        bound_tool=confirmation.tool_id if approved else None,
                        skip_reason=None if approved else SkipReason.APPROVAL_DENIED,
                        started_at=_AT if approved else None,
                        finished_at=_AT if approved else None,
                    ),
                ),
                updated_at=_AT,
            ),
            step_id="step-1",
            tool_id=confirmation.tool_id,
        )
        # Answered once, and now **retained** rather than forgotten (ADR-0198 §1).
        # The eviction above and this write are one step with no ``await`` between
        # them, which is §1's same-critical-section clause as this fake can state it:
        # there is no instant at which the handle names neither a park nor a settled
        # record. The state is filed where a restatement re-reads it from, never
        # carried on the record itself (§2).
        self.executions[resolved.state.id] = resolved.state
        self._retain(
            token.handle,
            _Settled(
                execution_id=resolved.state.id,
                step_id=resolved.step_id,
                tool_id=resolved.tool_id,
                disposition=resolved.disposition,
            ),
        )
        recipient_grant = await self._establish_recipients(
            token.handle,
            remember_recipients_until=until,
            answer=answered,
        )
        # ``turn`` is ``None`` here because this engine parks nothing from a live
        # turn — the shape a **recovered** park produces after a restart, which
        # ADR-0052 §3 ratifies. The *step* is what a resume is for and is always
        # present (ADR-0085 §4).
        return self._checked(
            TurnOutcome(turn=None, step=resolved, recipient_grant=recipient_grant), "resume"
        )

    def hold_confirmation_decision(self, handle: str, decision: PermissionDecision) -> None:
        """Bind a recorded ``CONFIRM`` to a park, so an establishing act can ride it.

        **A lever, because no sequence of surface calls reaches the state**, which is
        :meth:`park`'s own reason one record over. ADR-0235 §2 has the act ride *the
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

        Args:
            handle: The continuation handle the park is answered by.
            decision: The recorded ``CONFIRM``, as the trail holds it.
        """
        self._parked_decisions[handle] = decision

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

    def _check_establishable(self, handle: str) -> None:
        """Refuse an establishing act on a park it may not ride (ADR-0235 §2).

        The same two conditions §3 places on the recorded population, on the held
        one, and refused before anything is answered — so the park survives and the
        same token answers it again without the argument.

        Raises:
            UngrantableActError: If no recorded ``CONFIRM`` is bound to this park, if
                its ``egress_binding`` is not an
                :class:`~ai_assistant.core.types.EgressBinding`, or if that binding
                carries ``planned_with_external_content``.
        """
        confirmed = self._parked_decisions.get(handle)
        binding = None if confirmed is None else confirmed.egress_binding
        if not isinstance(binding, EgressBinding):
            msg = (
                "this confirmation records no egress call whose recipients could be made "
                "standing, so this answer establishes no recipient grant; the confirmation "
                "is unaffected and may still be answered (ADR-0235 §2)"
            )
            raise UngrantableActError(msg)
        if binding.planned_with_external_content:
            msg = (
                "this confirmation records a call planned over external content; you may "
                "approve such a call, and may not in that act make its recipients standing "
                "(ADR-0193 §2, §4; ADR-0235 §2)"
            )
            raise UngrantableActError(msg)

    def _establishing_instant(self, remember_recipients_until: datetime) -> datetime:
        """Read the clock once, and refuse an expiry that is not strictly after it.

        ADR-0235 §1: one reading, used for both the comparison and the answer this
        engine records, because two reads admit an expiry that passes the check and
        fails ``established_from``'s constructor.

        Raises:
            UngrantableActError: If the chosen instant is at or before that reading.
                The message names the instant it was compared against.
        """
        decided_at = self._recipient_now()
        if remember_recipients_until <= decided_at:
            msg = (
                f"a standing recipient grant expires strictly after the answer that "
                f"establishes it; {remember_recipients_until.isoformat()} is at or before "
                f"{decided_at.isoformat()}, the instant this answer would carry, so nothing "
                f"was recorded (ADR-0235 §1)"
            )
            raise UngrantableActError(msg)
        return decided_at

    async def _record_the_answer(
        self, handle: str, *, at: datetime, approved: bool
    ) -> PermissionDecision:
        """Author and record the resolving decision this act rides (ADR-0193 §2).

        Called **before** the park is evicted, so a trail that refuses the write
        leaves the park exactly where it was and the token still answerable — the
        order the concrete engine has, where the runner records inside the critical
        section that later replaces the park with its settled record.

        **On both answers**, because ADR-0042 §4 guarantees the ``DENY``'s record and
        ADR-0235 §4's ``DECLINED`` asserts it on the carrier. This engine holds no
        ``ActionPolicy``, so the ruling is the one an approving or declining answer
        produces; a consumer wanting a policy that declines an *approving* answer is
        exercising a hub's own thresholds rather than this double.

        Args:
            handle: The park being answered.
            at: The instant to stamp, which on an approving answer is the one
                ADR-0235 §1's expiry was already compared against.
            approved: What the user said.

        Returns:
            The recorded resolving decision.

        Raises:
            AuditError: If the trail refuses the answer. It propagates, because a
                trail that will not hold the record of a decision is not a state
                this engine may report an outcome over.
        """
        confirmed = self._parked_decisions[handle]
        answer = PermissionDecision.from_confirmation(
            confirmed,
            _approving(confirmed) if approved else _declining(),
            id=f"decision-{handle}-answer",
            decided_at=at,
        )
        await self.trail.record(answer)
        return answer

    async def _establish_recipients(
        self,
        handle: str,
        *,
        remember_recipients_until: datetime | None,
        answer: PermissionDecision | None,
    ) -> RecipientGrantOutcome | None:
        """Say what became of the act this ``resume`` collected.

        Reached **after** the step has executed and settled, so nothing here raises
        and everything here is reported on the carrier (ADR-0235 §6). The three
        refusing members are read from the **type** of the refusal ``record`` raised
        and from nothing else — no message is parsed, no count taken, and no listing
        read afterwards (ADR-0235 §11).

        ``answer`` is ``None`` on the one path that collected the act and reached no
        approving answer: ``approved=False``, where the ``DENY`` is recorded and the
        store is never reached (ADR-0235 §2, §4).
        """
        if remember_recipients_until is None:
            return None
        if answer is None or answer.ruling.outcome is not PermissionOutcome.ALLOW:
            # The one member that never reaches the store (ADR-0235 §4): the
            # resolving ruling was not an ``ALLOW``, so no grant could be established
            # from it and ``RecipientGrantStore.record`` was not called at all.
            return RecipientGrantOutcome(not_established=RecipientGrantNotEstablished.DECLINED)
        grant = RecipientGrant.established_from(
            self._parked_decisions[handle],
            answer,
            id=f"recipient-grant-{handle}",
            expires_at=remember_recipients_until,
        )
        # **The mapping is reached for rather than restated** (ADR-0235 §4, §11): a
        # second copy of "which member does this refusal mean" would let a
        # consumer's tests certify against a hub that answers differently.
        return await record_the_grant(self.recipient_grants, grant)

    def _retain(self, handle: str, settled: _Settled) -> None:
        """Record one answered binding under its handle, within ADR-0198 §4's bound.

        The bound is ``max_outstanding_confirmations`` and no figure is invented: the
        number of answers a client can be uncertain about at once is bounded by the
        number of tokens it can hold at once. A **count**, never a lifetime — no
        clock is read, so nothing here makes a token's answerability depend on how
        long a user stared at a page — and the discard is the **least recently
        settled**, which this table's insertion order already is, since a handle
        settles at most once and a restatement reads without re-inserting.
        """
        while len(self.settled) >= self._max_outstanding:
            self.settled.pop(next(iter(self.settled)))
        self.settled[handle] = settled

    def _restate(self, handle: str) -> TurnOutcome:
        """Say what a settled binding was decided, or refuse a token naming nothing.

        The restatement's shape is ADR-0170 §4's second one exactly (ADR-0198 §2):
        ``turn`` ``None``, ``routed`` ``None``, ``reply`` ``None`` and
        ``reply_degraded`` ``False``, beside a ``step`` carrying the resolution's
        immutable facts and a ``confirmation`` of ``None`` — which the type's own
        validator already requires of a disposition that is not
        ``AWAITING_CONFIRMATION``.

        **The state is re-read here and never cached at settlement.**
        ``StepOutcome.state`` is the durable execution state after the last transition
        committed, and a value snapshotted at settlement stops being that the moment
        anything advances the execution (ADR-0139 §2). Where :attr:`executions` no
        longer holds it — the fake's spelling of a plan store that has dropped it —
        this raises ``PlanningError`` and asserts nothing about the outcome, because
        an outcome it cannot read is not one it may state.

        Args:
            handle: The continuation handle presented, naming no park.

        Returns:
            The restated outcome.

        **The refusal names both remedies, because at this point the two kinds of
        park are indistinguishable.** A handle reaching here is a step park unknown,
        aged out of ADR-0198 §4's bound or minted by an earlier engine — for which
        ``pending_confirmations`` re-mints a token — *or* a routed park already
        claimed, for which ADR-0197 §7 rules that ``pending_confirmations`` "does
        **not** list a routed park" and the remedy is §7's own sentence: nothing has
        happened yet, so the operation is asked for again rather than resumed again.
        Naming only the first would teach a surface the one remedy that cannot help a
        routed token, and this fake is what every interface adapter's tests are
        written against — so it states what ``Engine._restate`` states (#1653).

        Args:
            handle: The continuation handle presented, naming no park.

        Returns:
            The restated outcome.

        Raises:
            UnknownContinuationError: If the handle names no settled record either —
                unknown, minted by an earlier engine, discarded under ADR-0198 §4's
                bound, or a **routed** park already claimed (ADR-0197 §7).
                **Never a denial** (ADR-0084 §7).
            PlanningError: If the settled binding's execution is no longer held.
        """
        settled = self.settled.get(handle)
        if settled is None:
            msg = (
                "this token names no step awaiting confirmation in this engine, and no answer "
                "this engine still holds; it may be from an earlier run of the process, or its "
                "answer may have aged out. If it named a routed operation, this engine can no "
                "longer say whether that operation ran: a routed park is evicted the moment it "
                "is claimed, is never listed and is never re-minted, so ask for the operation "
                "again rather than resuming this token, and the answer will say what it finds. "
                "If it named a parked step, pending_confirmations() re-mints a token for any "
                "park that is still answerable"
            )
            raise UnknownContinuationError(msg)
        state = self.executions.get(settled.execution_id)
        if state is None:
            msg = f"the store no longer holds execution {settled.execution_id!r} for this token"
            raise PlanningError(msg)
        restated = StepOutcome(
            disposition=settled.disposition,
            state=state,
            step_id=settled.step_id,
            tool_id=settled.tool_id,
            confirmation=None,
        )
        return self._checked(TurnOutcome(turn=None, step=restated), "resume")

    # --- the two accumulation legs ----------------------------------------

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Fold one piece of feedback into memory, storing exactly one belief."""
        check_arguments("learn", max_bytes=self._max_payload_bytes, event=event)
        self.calls.append(("learn", {"event": event}))
        record_id = f"rec-{len(self.beliefs_held) + 1}"
        self.hold(record_id, content=event.content)
        outcome = LearnOutcome(
            results=(
                IngestSummary(
                    decision=LearnDecision.STORED,
                    record_id=record_id,
                    reason="the fake engine stores what it is told",
                ),
            )
        )
        return self._checked(outcome, "learn")

    async def observe(self, *, conversation_id: Identifier | None = None) -> ObservationReport:
        """Report what a passive observation pass would have done."""
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        check_arguments("observe", max_bytes=self._max_payload_bytes, conversation_id=selected)
        self.calls.append(("observe", {"conversation_id": selected}))
        if selected is not None and selected not in self.conversations_held:
            msg = f"no conversation {selected!r}"
            raise UnknownConversationError(msg)
        return self._checked(self.observation, "observe")

    # --- the inspection surface -------------------------------------------

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
        """Destroy one belief, reporting whether there was one to destroy."""
        named = identifier(record_id, name="record_id")
        check_arguments("forget", max_bytes=self._max_payload_bytes, record_id=named)
        self.calls.append(("forget", {"record_id": named}))
        # The placement goes with the record: `forget` destroys rather than retires,
        # so leaving the entry would let a later belief minted at a recycled id
        # inherit a placement nobody set on it.
        self.placements.pop(named, None)
        return self._checked(self.beliefs_held.pop(named, None) is not None, "forget")

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
        """Show the count and span destroying one conversation would destroy."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments("conversation", max_bytes=self._max_payload_bytes, conversation_id=named)
        self.calls.append(("conversation", {"conversation_id": named}))
        return self._checked(self.conversations_held.get(named), "conversation")

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Destroy one conversation, reporting whether there was one to destroy."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_conversation", max_bytes=self._max_payload_bytes, conversation_id=named
        )
        self.calls.append(("forget_conversation", {"conversation_id": named}))
        self.activity.pop(named, None)
        return self._checked(self.conversations_held.pop(named, None) is not None, "forget")

    # --- the transcript archive (ADR-0225 §5, §6, §7) ----------------------

    # **Relayed to :attr:`archive` rather than reimplemented here**, which is
    # ``spend_totals``' reason applied to a second store: ADR-0225 §6 and §7 make the
    # read-time retention predicate, the matching predicate, the total order, the
    # excerpt bound and both size figures the **archive's** guarantees, so a fake
    # engine computing any of them would be a second implementation of a rule the
    # shared suite could then only compare against itself. What is asserted here is
    # what this surface owes: the local argument refusals, and that each call reaches
    # the seam at all.
    #
    # **Seeded through the archive, because nothing on this seam can create an
    # entry** (§10): ``engine.archive.hold(entry)`` is how a consumer arranges a
    # history, exactly as ``notification_store`` is seeded for the notification
    # surface. The wide seam carries no ``append``, and the fake does not grow one.

    async def transcript_search(
        self,
        query: NonBlankEncodableText,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[TranscriptHit, ...]:
        """Search the held transcript lexically, newest first."""
        asked = non_blank_text(query, name="query")
        positive_page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "transcript_search",
            max_bytes=self._max_payload_bytes,
            query=asked,
            limit=limit,
            offset=offset,
        )
        self.calls.append(("transcript_search", {"query": asked, "limit": limit, "offset": offset}))
        # The query is relayed **unstripped**: ``non_blank_text`` refuses a blank and
        # returns what it was given, so a query whose leading space is significant
        # still is one here (ADR-0225 §10).
        found = await self.archive.search(asked, limit=limit, offset=offset)
        return self._checked(tuple(found), "transcript_search")

    async def transcript_conversation(
        self,
        conversation_id: Identifier,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[TranscriptEntry, ...]:
        """Read one conversation's transcript, in ordinal order."""
        named = identifier(conversation_id, name="conversation_id")
        positive_page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "transcript_conversation",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
            limit=limit,
            offset=offset,
        )
        self.calls.append(
            (
                "transcript_conversation",
                {"conversation_id": named, "limit": limit, "offset": offset},
            )
        )
        held = await self.archive.conversation(named, limit=limit, offset=offset)
        return self._checked(tuple(held), "transcript_conversation")

    async def transcript_entry(self, address: Identifier) -> TranscriptEntry | None:
        """Read one entry whole, or report that nothing is held at that address."""
        named = identifier(address, name="address")
        check_arguments("transcript_entry", max_bytes=self._max_payload_bytes, address=named)
        self.calls.append(("transcript_entry", {"address": named}))
        return self._checked(await self.archive.entry(named), "transcript_entry")

    async def transcript_entries(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[TranscriptEntry, ...]:
        """Enumerate every entry held — the archive's export (ADR-0225 §7)."""
        positive_page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        check_arguments(
            "transcript_entries", max_bytes=self._max_payload_bytes, limit=limit, offset=offset
        )
        self.calls.append(("transcript_entries", {"limit": limit, "offset": offset}))
        held = await self.archive.entries(limit=limit, offset=offset)
        return self._checked(tuple(held), "transcript_entries")

    async def forget_transcript_entry(self, address: Identifier) -> bool:
        """Destroy one transcript entry, reporting whether one was there."""
        named = identifier(address, name="address")
        check_arguments("forget_transcript_entry", max_bytes=self._max_payload_bytes, address=named)
        self.calls.append(("forget_transcript_entry", {"address": named}))
        return self._checked(await self.archive.discard(named), "forget_transcript_entry")

    async def forget_transcript_conversation(self, conversation_id: Identifier) -> int:
        """Destroy one conversation's transcript, reporting how many entries went."""
        named = identifier(conversation_id, name="conversation_id")
        check_arguments(
            "forget_transcript_conversation",
            max_bytes=self._max_payload_bytes,
            conversation_id=named,
        )
        self.calls.append(("forget_transcript_conversation", {"conversation_id": named}))
        return self._checked(
            await self.archive.discard_conversation(named), "forget_transcript_conversation"
        )

    async def transcript_archive_size(self) -> TranscriptArchiveSize:
        """Relay the archive's own two figures, unnetted (ADR-0225 §6)."""
        self.calls.append(("transcript_archive_size", {}))
        return self._checked(await self.archive.size(), "transcript_archive_size")

    # --- durable recovery --------------------------------------------------

    async def pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Hand back every park that is still answerable, with a resolvable token."""
        self.calls.append(("pending_confirmations", {}))
        return self._checked(tuple(self.parked.values()), "pending_confirmations")

    # --- the grant surface (ADR-0102 §1) -----------------------------------

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

    def start_conversation(self, conversation_id: str) -> str:
        """Record one conversation, and return its id.

        Its activity stamp starts one tick later than the last conversation's, so
        "most recently active first" is a fact the ordering can be tested against
        rather than an accident of a fixed clock.
        """
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

    def park(
        self, handle: str, *, tool_id: str = "t-1", egress: EgressBinding | None = None
    ) -> Confirmation:
        """Park one confirmation this engine will resolve, and return it.

        **The egress member is reduced from the binding by the same rule the real
        engine uses** (ADR-0178 §5): ``account_identity`` from
        ``egress.account.identity``, ``spans`` from ``egress.spans``, and each of
        ``planned_with_external_content`` and ``coverage`` transcribed from the
        binding's own (ADR-0181 §3, ADR-0233 §4) — never a constant of this fake's,
        which would be the second carriage those clauses forbid. ``None`` where no
        binding is given. That identity is what makes this fake a
        producer the shared contract's ADR-0178 §3 clause can be held to — a fake
        assembling the member some other way would pass a suite written against
        itself.

        Args:
            handle: The continuation handle this park is answered by.
            tool_id: The parked call's tool.
            egress: The binding the ruling was taken over, or ``None`` for a
                non-egress ``CONFIRM``. Reduced here rather than accepted
                pre-reduced, so the reduction is the thing under test.

        Returns:
            The parked confirmation.
        """
        confirmation = Confirmation(
            tool_id=tool_id,
            tool_description="a tool the fake engine parked",
            parameters={},
            reason="the policy wants a human answer",
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
        )
        self.parked[handle] = confirmation
        return confirmation

    def park_routed(
        self, handle: str, *, operation: RoutableOperation, subject: RoutedListing
    ) -> OperationConfirmation:
        """Park one routed confirmation this engine will resolve, and return it (§7).

        The routed twin of :meth:`park`, and it exists for that method's reason: a park
        is reached inside a turn, so an implementation has to be handed to a suite
        already holding one. ADR-0197 §7 makes a routed park doubly unreachable from the
        surface — ``pending_confirmations`` does not list it, and no durable store
        recovers it — so a lever is the *only* way a conformance case can reach the
        resume path at all.

        The card is assembled here rather than accepted pre-built, so what the shared
        suite holds this fake to is the type's own invariants: exactly one subject, of
        the arm ``operation`` names.

        Args:
            handle: The continuation handle this park is answered by.
            operation: Which confirm-owed operation is waiting on the user's answer.
            subject: The display subject, as a one-element listing.

        Returns:
            The parked confirmation, whose token the caller relays back to
            :meth:`resume`.
        """
        confirmation = OperationConfirmation(
            operation=operation, subject=subject, token=ContinuationToken(handle=handle)
        )
        self.routed_parked[handle] = confirmation
        return confirmation

    async def _resume_routed(self, handle: str, *, approved: bool) -> TurnOutcome:
        """Answer a routed park, and perform what the answer authorised (ADR-0197 §7).

        **Claimed once**: the entry is removed before anything is performed, so a second
        presentation of the token — whatever its ``approved`` value — falls through to
        :meth:`resume`'s unknown-token refusal.

        **The refusal is returned, never raised.** ``approved`` ``False`` yields
        ``RouteOutcome.REFUSED`` and no ``PermissionDeniedError``, because no
        ``ActionPolicy`` was consulted and no ``PermissionDecision`` recorded — ADR-0197
        §13's partial supersession of ADR-0042 §4, scoped to exactly this case.

        The operation is performed by calling this engine's own implementation of it
        (ADR-0197 §2), so a routed ``forget`` and a typed-door ``forget`` destroy the
        same belief through the same code.
        """
        card = self.routed_parked.pop(handle)
        operation = card.operation
        if not approved:
            outcome = RouteOutcome.REFUSED
        else:
            await self._perform_routed(card)
            outcome = RouteOutcome.PERFORMED
        # A routed pass that is not a park **owes an answer** (ADR-0197 §8), and this
        # one composes nothing — a fake originates no model call — so it carries the
        # fixed sentence below. Carrying `reply=None` instead would be the one routed
        # shape §8 refuses outright, so the fake could not even construct its own
        # outcome; carrying `reply_degraded=True` would claim a composition that failed.
        return self._checked(
            TurnOutcome(
                turn=None,
                routed=RoutedOperation(operation=operation, outcome=outcome),
                reply=_ROUTED_REPLY,
            ),
            "resume",
        )

    async def _perform_routed(self, card: OperationConfirmation) -> None:
        """Call this engine's own implementation of the card's operation (ADR-0197 §2).

        The scalar identity is read off the display subject by ADR-0197 §5's mapping —
        ``Belief.id``, ``Question.id``, ``SourceGrant.source`` — and it is the identity
        the façade is called with, never the record.
        """
        (subject,) = card.subject
        match card.operation:
            case RoutableOperation.FORGET:
                await self.forget(cast("Belief", subject).id)
            case RoutableOperation.FORGET_QUESTION:
                await self.forget_question(cast("Question", subject).id)
            case RoutableOperation.REVOKE:
                await self.revoke(cast("SourceGrant", subject).source)
            case RoutableOperation.GUARD:
                await self.guard(cast("Belief", subject).id)
            case RoutableOperation.UNGUARD:
                await self.unguard(cast("Belief", subject).id)
            case _:  # pragma: no cover — `OperationConfirmation` admits no read-only member
                msg = f"{card.operation.value} is read-only and is never confirmed"
                raise AssertionError(msg)

    # --- the clauses no type expresses -------------------------------------

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


def _declining() -> PermissionRuling:
    """The resolving ``DENY`` a declining answer produces.

    ``authorised_by`` is unset and refused if set: ``PermissionRuling`` admits an
    authorisation pointer on an ``ALLOW`` alone, which is the same "only the coherent
    outcome may carry this" rule the record's own lifetime validator uses.

    Returns:
        The ruling.
    """
    return PermissionRuling(
        outcome=PermissionOutcome.DENY,
        reason="the fake engine records the answer the user gave",
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


def _pieces_of(reply: str | None) -> tuple[str, ...]:
    """Split one composed answer into the chunks a stream of it would carry.

    **The join is the whole point** (ADR-0173 §3): the pieces concatenate back to
    ``reply`` exactly, so a chunk-reading client and a chunk-ignoring one hold the
    same answer. The split is *before* each word that follows whitespace, so every
    piece carries the separator that preceded it — which is also the shape ADR-0173
    §5's coalescing rule produces, rather than the tidy word-sized deltas §14 warns
    a fake will otherwise hide the interesting cases behind.

    An answer that owes no chunks — a park, a recovered resume, a composition that
    failed before publishing — yields none at all, which is the zero-chunk exchange
    ADR-0173 §4 admits.

    Args:
        reply: The composed answer, or ``None`` where the pass produced none.

    Returns:
        The pieces, in order, each carrying a non-whitespace character.
    """
    if reply is None:
        return ()
    pieces = _BEFORE_A_WORD.split(reply)
    # A leading run of whitespace is a piece with nothing in it, which
    # ``NonBlankEncodableText`` will not carry — so it is joined to the word after
    # it rather than dropped, which is ADR-0173 §5's own rule about a blank delta.
    while len(pieces) > 1 and not pieces[0].strip():
        pieces[1] = pieces[0] + pieces[1]
        del pieces[0]
    return () if not pieces[0].strip() else tuple(pieces)


def _refuse_unusable_report(
    report: SpokenDeliveryReport | None, *, conversation_id: str | None
) -> None:
    """The two local refusals ADR-0205 §1 and §2 place on a supplied report.

    A report beside no conversation names a turn that cannot exist — a fresh
    conversation contains none — and an ``UNKNOWN`` report is a value the hub writes
    and never one a caller supplies: a device that does not know reports nothing, and
    the absence of a report is spelled by omitting the argument.

    Both are before any I/O, which is ADR-0085 §3's convention for a malformed
    argument, and both are spelled here rather than shared with the engine's twin
    because ``testing`` depends on ``core`` and what keeps the two agreeing is the
    shared conformance suite that drives both.

    Raises:
        ValueError: If either refusal applies.
    """
    if report is None:
        return
    if conversation_id is None:
        msg = (
            "a delivery report names a turn of a conversation, and a fresh conversation "
            "contains no turn one could name; supply the conversation this report is "
            "about, or no report (ADR-0205 §1)"
        )
        raise ValueError(msg)
    if report.delivery.state is SpokenDeliveryState.UNKNOWN:
        msg = (
            "a device that does not know reports nothing: UNKNOWN is what this hub writes "
            "for an unreported turn, and the absence of a report is spelled by omitting "
            "the argument (ADR-0205 §2)"
        )
        raise ValueError(msg)


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
    """A turn whose plan has no step — a real ratified shape, not a stub."""
    goal = Goal(
        id="g-1",
        statement=utterance,
        provenance=Provenance(source=MemorySource.USER_ASSERTED, confidence=1.0, last_updated=_AT),
        created_at=_AT,
    )
    return TurnResult(
        goal=goal,
        context=CurrentContext(
            now=_AT,
            time_of_day=TimeOfDay.AFTERNOON,
            is_weekend=False,
            within_working_hours=True,
        ),
        memories=(),
        plan=ActionPlan(id="p-1", goal_id=goal.id, steps=(), created_at=_AT),
    )


__all__ = ["FakeAssistantEngine"]

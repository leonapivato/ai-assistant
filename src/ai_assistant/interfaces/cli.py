"""Command-line interface — the first adapter onto the engine (ADR-0042 §7).

Kept intentionally thin (golden rule 3, ADR-0042 §6): it parses input into an
utterance, obtains the façade from the composition root, drives one turn with
``converse``/``resume``, renders the final :class:`~ai_assistant.orchestration.TurnOutcome`
with Rich, relays the **opaque** continuation token on a confirmation, and closes
the façade on exit. It authors no permission ruling, plans nothing, selects no
tool, and touches no subsystem directly — all of that is the engine's, reached
only through the façade (ADR-0042 §6). Registered as the ``assistant`` console
script in ``pyproject.toml``.

``beliefs`` and ``forget`` are the belief-inspection surface (ADR-0073 §7): they
render what the engine already computed and destroy what the user names. The
*band* on each row arrives on the DTO — :meth:`~ai_assistant.orchestration.Belief`
is projected in the engine so ADR-0072 §1's classification never lands here — and
this module reads no clock for them and re-filters nothing. The same holds for
ADR-0077 §6's evidence: citations arrive already resolved to readable content or
to a tombstone, and the confidence on the DTO is already the presented one, so
nothing here resolves a citation, computes an adjustment, or ever sees an id it
could pass off as a warrant.

``conversations`` and ``forget-conversation`` are the conversation surface
(ADR-0074 §2, §8, §10), and ``ask --conversation`` is how a turn continues one.
Continuation is deliberately **an option on ``ask`` and never a second meaning for
``resume``**, which transports consent for a parked confirmation: overloading that
verb would put two unrelated flows behind one word in the surface where the
distinction matters most. A conversation the user deleted reaches none of these —
not because anything here filters it, but because the store hides a stamped
conversation from every read that presents one.

``transcript`` is the archive's surface (ADR-0225 §8), and it is a **group of its
own** rather than a mode of either of the two above: §8 requires the archive's reads
and destroys to "live on their own command, distinct from ``beliefs`` and from
``conversations``", so that no surface presents a transcript entry as a belief, as
something the assistant holds, or as evidence for anything. Every read there prints
what it is showing and the archive's own size beside it without being asked (§6, §8),
and the two destroys under it reach a conversation the ``conversations`` surface has
already reclaimed — which is the whole point of the archive: reaching the retention
horizon evicts a turn from the working set rather than destroying it.

``observe`` is the accumulation surface (ADR-0077 §8, §9.8): it asks the engine to
read back one conversation's recent turns, and renders what was proposed, what the
gate did with each proposal, and **which model route read the transcript**. It is
explicit by design — nothing here polls, schedules, or observes as a side effect of
another command — and it renders a deferred proposal's citations in full, because no
later view resolves them (#431).

``questions``, ``answer`` and ``forget-question`` are the deferred-question surface
(ADR-0078 §8): a memory decision the gate would not make without the user's word now
waits durably, and this is where it reaches them. The two enumerations stay
**separate** — the answerable questions, and the ones whose answer was begun and whose
outcome was never recorded — because an interrupted question is not answerable and
offering it beside the others would present a claim that cannot be taken. Answering is
binary; there is deliberately **no verb that claims to retry an apply**, because the
system does not know whether the interrupted write landed and a verb implying it does
would be the one dishonest line on this surface. This module renders what the engine
computed and mints no authority: the ``UserConfirmation`` an accept carries is
constructed in `orchestration`, from a claim, and an adapter can neither build one nor
see one.

``sources``, ``grant``, ``revoke`` and ``grants`` are the grant surface (ADR-0097
§9, ADR-0102 §1): the four operations by which a person connects a source, says
what may be read from it, withdraws that, and reads back what they decided. A
source is **chosen from what the hub offers and never typed**, so no path can enter
a durable, exportable, user-rendered record (ADR-0097 §1, §9).

Two obligations land on *this module* rather than on the engine, and both are
unenforceable from the hub's side — nothing on the wire distinguishes a client that
honoured them (ADR-0098 §5). **``grant`` renders the source's configured location
and takes an explicit act before it sends anything** (ADR-0102 §6), which is why it
enumerates first and refuses to grant anything the enumeration did not carry: a
grant nobody was shown is one step from the state ADR-0097 §8 forbids, where
configuration presents itself as consent. And **a revocation is never presented as
having stopped a read in flight** (ADR-0102 §9) — what is true is that no *further*
read starts and nothing a running read produces is used, and ADR-0097 §5a
explicitly declines to promise more.

``revoke`` deliberately has **no ceremony**, where ``forget`` has one: forgetting
destroys a belief and ADR-0073 §5 requires the thing be shown first, while revoking
destroys nothing and is the user's whole remedy, which ADR-0102 §4 says nothing may
stand between them and.

``notifications``, ``dismiss``, ``forget-notification``, ``notification-settings``
and ``tune`` are the notification surface — exactly the five engine operations
ADR-0130 §9 ratifies and no sixth. Four of them relay one call each; ``tune`` reads,
substitutes what the user named, and writes the whole value back, which is the flow
``AssistantEngine.set_notification_preferences`` itself prescribes ("a caller
changing one setting reads, adjusts and writes back") together with its consequence,
that two writers racing lose the earlier one's edit.

**The write is the half that makes the rest reachable, and that is ADR-0130 §6's
design rather than this module's.** Every class defaults to ``hold``, so out of the
box nothing interrupts and the first interruption follows a deliberate act by the
user; before this surface existed the act had no door and the default could not be
moved (#979). ``tune``'s help therefore names the three independent acts that arm
proactive contact end to end — the operator's interval setting, the user's
``notify`` grant, and the reach raise — because none of them implies another
(ADR-0132 §4, ADR-0133 §3, ADR-0130 §6) and a record of them was until now in ADR
bodies alone (#981).

The ruling, its reason and the conditions it is waiting on all arrive on the
record; this module re-rules nothing, re-orders nothing, and computes no reach.
Its **one** clock reading is the listing's, taken once per page: ADR-0130 §7 has
an expired record stay enumerable and render *as expired*, no field says which
side of that line a record is on, and the comparison itself belongs to the core
type — so what the adapter supplies is the reading, exactly as it does when it
stamps a ``FeedbackEvent``. It answers expiry and nothing else: dismissal and a
``DROP`` are stamped by the hub and are taken as final. On a remote hub the
reading is this device's, so a record within clock skew of its expiry may be
labelled from the wrong side; that moves a label and never a verb, the engine
staying the authority on what any act does.

``connect``, ``reconnect``, ``disconnect``, ``connections`` and ``connection-log``
are the connection surface — the five engine operations ADR-0151 §1 ratifies and
no sixth. They are **not** the grant surface and are never offered as an
alternative to it: a connection is not an authorisation, and nothing here is a
list of what the assistant may do (ADR-0151 §12).

Four obligations land on *this module* and none of them is enforceable from the
hub's side (ADR-0098 §5), which is why ADR-0151 §16's client lane owes each as a
test here. **The identity is displayed as part of the act** (§5) — a person
pasting a token into the name field is caught by seeing it, and a client that
swallowed the value would remove the one ingredient that failure needs. **A
``PENDING`` record is rendered as not connectable** (§4), never as a connection
being established or one that completes on its own: nothing is running, and
ADR-0148 §6 rules the state "refused rather than reconciled". **A partial outcome
is reported as the half that landed** (§7) — the vocabulary is ADR-0139 §4's,
which §7 transposes from an amendment's two calls to one act's three writes, and
the resolution is always a *read* rather than a second write, because the write a
hopeful client would send carries a credential. And **a disconnection says what
was removed and never more** (§8): a ``None`` is not a report of a disconnection,
and disconnecting every reference is not ADR-0149 §8's purge.

The credential is **prompted and never an argument**, so it does not land in a
shell history, a process listing or an argv-reading log; ``--credential-stdin``
is the scriptable door, and it strips the line terminator alone because ADR-0125
§3 makes two spellings of a secret two different secrets.

``decisions`` and ``export-decisions`` are the audit surface — the two engine
operations ADR-0186 §1 promotes and no third (§9). They are the first door onto
the permission trail: ADR-0021 §4 assigns ``export`` the discharge of ADR-0004
§6's portability obligation for this store, and until these landed it was
discharged to nobody a user could reach (#1485). They are **not** the grant
surface and answer none of its questions: ``assistant granted`` says what may be
reached, and a row here says what was ruled about one act.

Three obligations land on *this module*, and each is a sentence a person reads.
**A row is rendered whole or not at all** (ADR-0186 §7): nothing here truncates,
summarises, samples or counts in place of any part of one, so a narrow terminal
gets fewer rows rather than shorter ones. **The call's origin is rendered in
three states** — the material this system selected included a record marked as
resting on recorded external content, it did not, or the origin was **never
recorded** — the third distinct from the other two and never shown as ``False``,
as "no", or as an absence (ADR-0184 §2, ADR-0186 §7). And **a row is never
rendered as a live permission, a transmission, or a question still open**
(ADR-0186 §8): nothing here composes a
:class:`~ai_assistant.core.types.Confirmation`, offers an approval control,
computes ``authorises``, or says a call went anywhere. ``resume`` is where a
parked question is answered, and it is a different surface.

**The export is one JSON document on standard output and nothing else on that
stream** (ADR-0186 §9): the array of the decisions' own
``model_dump(mode="json")`` projections, faithful, with no key added, removed,
renamed or annotated — so it re-validates as ``tuple[PermissionDecision, ...]``,
and a row recorded before ADR-0181 §3 carries no ``planned_with_external_content``
key at all, the absence being the state. Diagnostics and errors go to standard
error. There is deliberately no ``--output``: a path, an overwrite policy and a
partial-write story in an adapter are decisions about the user's data made in the
wrong layer (golden rule 3). The bare name ``export`` stays **reserved** for
ADR-0004 §6's whole-installation artifact, which neither of these discharges
(#1502).

``reads`` and ``export-reads`` are the same pair one store over — ADR-0186 §10's
**second pair**, over the record of the attempts this system made to read a
source (ADR-0185). The two trails **partition** the subject: a read is never a
:class:`~ai_assistant.core.types.PermissionDecision` and an egress is never a
:class:`~ai_assistant.core.types.SourceReadRecord`, so neither pair answers the
other's half and neither is presented as though it did. §10's inheritance is what
binds this module — §7's last two clauses (a row is rendered whole or not at all;
every value is inserted as **data**) and §8's bars on liveness, on authorisation
and on event wording, the last transposed to this store: a row states what was
*attempted*, never what came of it. What §10 does **not** inherit here is §7's
egress content floor, which is about a binding no read record carries.

**A refused read is a row and is rendered as one** (ADR-0185 §7). It is the row
the trail exists for: "was this source read after I revoked it" is answered
positively rather than by an absence, which in a pruning store is ambiguous by
construction. So ``assistant granted`` still says what may be reached and this
says what was attempted, and neither reports the other — no read, read count or
last-read instant appears beside a standing grant (ADR-0139 §6, ADR-0185 §8).

**The two exports are not equally complete, and that is said here rather than
left to be discovered** (ADR-0186 §10). ``export-decisions`` writes every ruling
its trail holds, and that trail prunes nothing (#108). ``export-reads`` writes the
**horizon**: the store holds at most ``Settings.source_read_trail_max_rows``
records and deletes the earliest-recorded first (ADR-0185 §6), so attempts older
than the cap are gone, ADR-0004 §6's export right is discharged "to that extent
and no further" (ADR-0185 §9, §10), and no lane may report it as a complete
history. ADR-0185 §5a's two paths are the second reason no surface here says
"every read", and the two are **not** the same shape: a recorder that raised
leaves a read that ran with **no** row, while a cancellation landing after the
read began leaves none where it landed before the recorder call and an
**indeterminate** state where it landed inside one already in flight — ADR-0060's
rule that a cancelled write may or may not have committed, and §5a forbids
assuming either result. §10 measures the exit over attempts "driven to an outcome
with a recorder that answered" for exactly that reason. Neither path is licence
to leave an access unrecorded; both are places the mechanism does not reach, and a
surface that papered over them would be claiming a completeness the store does
not have.

``invocations`` and ``export-invocations`` are the **third** pair, over the audit
trail again and over a different row kind — what this system *did* on an
authorisation, which ADR-0192 §4 promotes as two more engine operations and no
third. §4 bounds the adapter set by one and leaves the choice here: this is the
surface that already renders the decision trail, so the act taken under a ruling
lands beside the ruling. The two answers are **two sequences and never one**: no
operation returns a mixed one, and nothing here presents a decision row as a
transmission, an invocation row as a ruling, or a joined pair as a single record.

**Three of ADR-0192 §4's clauses land on this module and each is a sentence the
renderer refuses to write.** A *call begun* is never rendered as pending, open,
in flight, awaiting an outcome, or as having no completion yet — no row carries
that fact, and establishing it would need the join across two answers §4 forbids
a surface making. Nothing is said or implied about anything being received,
delivered or acted on by any recipient, on any row, in any state, and no
recipient, account, endpoint or destination is named on an invocation row: the
row carries none, and who a ruling was taken over is ``assistant decisions``'
under ADR-0186 §7's floor. And the word **sent** is withheld even on a successful
outbound call — ADR-0031 §4 bounds ``SUCCEEDED`` to a validated callable return,
an unexpired deadline and no increase in the cancellation count, none of which is
a transmission — so what such a row says is that the call was *attempted and
reported success*, which is the one statement §4 licenses and only on that one
state.

**An absence is stated as one, twice over** (ADR-0192 §4, ADR-0184). A completion
whose outcome is not ``SUCCEEDED`` and which reports no failure kind renders
**that no kind was reported**, never a kind this module chose and never a blank;
and a cost whose basis is ``UNKNOWN`` renders **that it is not known**, never a
zero, a dash or "free" — an unknown price and a free one being the distinction
:class:`~ai_assistant.core.types.ToolCost` exists to keep apart.

v1 renders the *final* state of each call; streaming is deferred (ADR-0042 §5).
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import math
import re
import shlex
import sys
from datetime import UTC, datetime, time, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Final, NamedTuple, TextIO, assert_never, cast, final

import typer
from pydantic import SecretStr
from rich.console import Console
from rich.markup import escape
from rich.text import Text

from ai_assistant import __version__
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import (
    AssistantError,
    ConfigurationError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    InvalidResolutionError,
    OversizedValueError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    UnknownConnectionError,
    UnusableIdentityError,
)
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    DEFAULT_NOTIFICATION_REACH,
    DEFAULT_PAGE_SIZE,
    SECRET_VALUE_MAX_BYTES,
    AnswerKind,
    Belief,
    BeliefBand,
    ClassReach,
    CostBasis,
    DiscloserProvenance,
    Disposition,
    FeedbackEvent,
    FeedbackKind,
    GrantScope,
    LearnDecision,
    MemoryKind,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    ProvisioningState,
    Question,
    QuestionState,
    QueueOutcome,
    QuietWindow,
    ReadOutcome,
    RecordedInvocation,
    ReplyChunk,
    RoutableOperation,
    RouteOutcome,
    SecretScope,
    SourceGrant,
    SourceReadRecord,
    SpendPeriod,
    SpendTotal,
    StepStatus,
    ToolOutcome,
    encodable_text,
    routed_listing_arm,
    secret_value,
)
from ai_assistant.interfaces.gateway import Disclosure, Note, run_gateway
from ai_assistant.secret_store import KeyringSecretStore
from ai_assistant.wire import (
    HubClient,
    HubEngineClient,
    LoopbackDestination,
    RemoteDestination,
    RemoteHubEngineClient,
    TransportError,
    destination,
    local_agent,
    remove_enrolment,
    store_enrolment,
)
from ai_assistant.wire.address import check_socket_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import (
        AnswerOutcome,
        BeliefSummary,
        CanonicalDestination,
        Confirmation,
        ConfirmationDestination,
        ConfirmationEgress,
        ConnectedAccount,
        ConnectionAct,
        ConversationDigest,
        ConversationSummary,
        DestinationProtocol,
        EgressBinding,
        EgressSpan,
        GrantableSource,
        HeldNotification,
        IngestSummary,
        LearnOutcome,
        NotificationCandidate,
        ObservationReport,
        ObservedProposal,
        OperationConfirmation,
        QueuedQuestion,
        RoutedListing,
        RoutedOperation,
        StepOutcome,
        ToolCost,
        ToolInvocation,
        TranscriptArchiveSize,
        TranscriptEntry,
        TranscriptHit,
        TurnOutcome,
        Warrant,
    )

app = typer.Typer(
    name="assistant",
    help="A model-agnostic AI operating system — deeply personalized assistant.",
    no_args_is_help=True,
    add_completion=False,
)

#: The two acts ADR-0124 performs **at the device**, grouped so they are not
#: mistaken for the hub's. Enrolling a device is a decision only the owner can make
#: *at the hub* (§6) and is `ai-assistant-device enrol` on the hub's own machine;
#: what these do is store what that printed, and remove it again (§8).
device_app = typer.Typer(
    name="device",
    help=(
        "What this device holds about a hub: store the enrolment the hub printed, "
        "or remove it. Enrolling a device is done at the hub, with "
        "'ai-assistant-device' on the hub's own machine."
    ),
    no_args_is_help=True,
)
app.add_typer(device_app, name="device")

#: The transcript archive's own command group (ADR-0225 §8). **Its own, and never a
#: mode of ``beliefs`` or ``conversations``**: §8 puts the archive's reads and
#: destroys on a command of their own so that nothing here presents a transcript
#: entry as something the assistant believes. What it holds is what §7 and §5 admit
#: and nothing else — four reads and two destroys — with §6's size report rendered
#: beside every read rather than offered as a seventh command, because the figure is
#: owed *unasked* and a command the user must think to run is one they never do.
transcript_app = typer.Typer(
    name="transcript",
    help=(
        "Search and read what was actually said, and destroy any of it. A record of "
        "the exchange, kept apart from what I believe: nothing here reaches a reply."
    ),
    no_args_is_help=True,
)
app.add_typer(transcript_app, name="transcript")
console = Console()

#: Where a diagnostic goes when standard output is carrying an **artifact**
#: (ADR-0186 §9, §10). ``export-decisions`` and ``export-reads`` each write one
#: JSON document to standard output
#: "and nothing else on that stream", so their error boundary cannot use
#: :data:`console` — a hub that is not reachable would otherwise put a sentence
#: where a user's shell expects the export. Every other command on this surface
#: keeps writing to :data:`console`, because a terminal reading a listing is not a
#: pipe reading a document.
#:
#: Neither console is given a ``file``, so each follows ``sys.stdout`` and
#: ``sys.stderr`` as they stand when it prints rather than as they stood at import.
error_console = Console(stderr=True)

#: Exit codes (ADR-0042 §7: "setting a meaningful exit code").
_EXIT_OK = 0
_EXIT_ERROR = 1

#: How ``--memory-kind`` defaults from ``--kind`` when the user does not give one —
#: **only where the value follows from what the user said** (ADR-0122 §2). Not
#: exhaustive over ``FeedbackKind``, deliberately: ``CORRECTION`` has no entry, and
#: a lookup that misses leaves the field ``None`` for ``orchestration`` to resolve.
#:
#: The two intents are not symmetric. A stated **preference** establishes a
#: ``PreferenceMemory`` by its own intent — the user is not pointing at a stored
#: belief, they are stating one — so no lookup is available and none is needed. A
#: **correction** points at a belief that already exists, and its record type is a
#: property of *that* belief; naming it here is not a default but a prediction, made
#: at the one layer with no access to the target. This table used to make it anyway,
#: citing ``FeedbackEvent``'s "a fact becomes a ``SemanticMemory``, not a
#: preference" — an *illustration* that a correction's type varies with what it
#: corrects, read as a rule that it is always semantic. That over-reading is #864:
#: every correction filed as a fact, and the kind-scoped conflict probe then looking
#: for its target only in the drawer this table named.
#:
#: Leaving it absent is the adapter reporting what it knows, which is what keeps
#: golden rule 3 intact — the resolution is business logic, and none of it happens
#: in ``interfaces/``.
_DEFAULT_MEMORY_KIND = {
    FeedbackKind.PREFERENCE: MemoryKind.PREFERENCE,
}

#: One human-readable line per :class:`~ai_assistant.orchestration.LearnDecision`,
#: rendered under a ``learn`` result. Exhaustive: every member has a message, so a
#: new decision surfaces at type-check time rather than as a missing line.
#:
#: ``DEFERRED`` is deliberately **absent**, because one line cannot cover it any
#: more (ADR-0078 §10 item 9). The deferral now usually parks a question the user
#: can answer, sometimes collides with one already asked, sometimes finds the queue
#: full, and — for secret-tier data — is still not answerable at all. Those are four
#: different sentences and the fact that distinguishes them arrives on the result, so
#: :func:`_deferred_message` reads it instead of a table looking it up.
_LEARN_MESSAGES = {
    LearnDecision.STORED: "Stored a new memory.",
    LearnDecision.REINFORCED: "Reinforced an existing memory.",
    LearnDecision.SUPERSEDED: "Replaced a prior memory.",
    LearnDecision.REJECTED: "Rejected — nothing was stored.",
    LearnDecision.STORED_TEMPORARILY: "Stored temporarily.",
}

#: The line a deferral that **cannot** be answered from here keeps — the wording
#: ``learn`` has carried since #422, retained verbatim for the one arm ADR-0078 does
#: not close (§1, §10 item 9). ADR-0078 makes it false for a question that *is*
#: queued, and it stays true for secret-tier data, which ADR-0004 §3 forbids a
#: durable file: nothing was queued, so there is nothing to answer. Dropping "yet",
#: which was a promise about a flow that has now arrived for every other arm.
_NOT_ANSWERABLE = "Not stored — this needs review, which cannot be done from here."

#: What a question in each state means for the user, at the moment ``learn`` tells
#: them an existing one stood in the way of theirs (ADR-0078 §7). Total over
#: :class:`~ai_assistant.orchestration.QuestionState` (:func:`_suppressor_message`),
#: because the three states that can suppress a key each need a *different* sentence:
#: rendering an interrupted answer as an answerable follow-up would advertise a
#: question the user cannot act on.
_SUPPRESSOR_MESSAGES = {
    QuestionState.OPEN: ("Not stored yet — the same question is already waiting for your answer:"),
    QuestionState.DECLINED: (
        "Not stored — you already declined this question. Forget it to be asked again:"
    ),
    QuestionState.INTERRUPTED: (
        "Not stored — an answer to this question was already begun and its outcome was "
        "never recorded:"
    ),
    # A settled question's key no longer speaks for it, so it cannot suppress a fresh
    # arrival (ADR-0078 §2). These three are unreachable through the queue's own
    # rules and are given honest lines anyway, rather than a wildcard that would read
    # as a decision nobody made.
    QuestionState.APPLIED: "Not stored — a matching question was already answered:",
    QuestionState.STALE: "Not stored — a matching question went stale:",
    QuestionState.REDEFERRED: "Not stored — a matching question raised a follow-up:",
}


#: The only endpoint form ``--quiet-window`` takes, and the only one it can hold
#: without changing: ``QuietWindow`` is minute-resolution and ``minute_of_day``
#: truncates seconds deliberately, so a finer endpoint would be accepted and then
#: rounded down with nothing said (:func:`_quiet_window`).
_HH_MM = re.compile(r"\d{2}:\d{2}")

#: One past the largest value ``--limit``/``--offset`` may take, mirroring the range
#: ``MemoryStore.list_beliefs`` refuses outside of (ADR-0073 §2). Checked here at
#: parse time because that refusal is a ``ValueError``, not an ``AssistantError``,
#: so it would escape the command's error boundary as a traceback (see
#: :func:`_page_argument`).
_PAGE_BOUND = 2**63

#: Where :func:`_stored_bytes` starts printing a rounded figure beside the exact one.
#: The exact count is never replaced by it: ADR-0225 §6 puts a *measurement* on the
#: screen, and the surface that reports it is the last place to round one away.
_MIB = 1024 * 1024

#: The ``learn`` command's enum-typed options, defined once at module scope. Typer
#: options for an ``Enum`` parameter are hoisted here rather than called inline in
#: the signature, the module-level-singleton form ruff's B008 requires (a plain
#: ``str``/``bool`` option is exempt, an enum-annotated one is not).
_LEARN_KIND_OPTION = typer.Option(
    ..., "--kind", help="Whether this corrects a fact ('correction') or states a preference."
)
_LEARN_MEMORY_KIND_OPTION = typer.Option(
    None,
    "--memory-kind",
    help=(
        "Which typed memory to establish. Defaults from --kind "
        "(correction -> semantic, preference -> preference); set it to override."
    ),
)

#: The ``beliefs`` command's enum-typed filters, hoisted to module scope for the
#: same reason the ``learn`` ones are. Each may be repeated; the values within one
#: flag are a union and the two flags compose by conjunction, which is the façade's
#: own rule relayed unchanged (ADR-0073 §1).
_BELIEFS_BAND_OPTION = typer.Option(
    None,
    "--band",
    help="Only show beliefs in this band (repeatable). Default: every band.",
)
_BELIEFS_KIND_OPTION = typer.Option(
    None,
    "--kind",
    help=(
        "Only show beliefs of this memory kind (repeatable). Default: every kind "
        "except 'episodic' — pass --kind episodic to see captured conversation turns."
    ),
)

#: What ``assistant beliefs`` selects when the user names no ``--kind`` (ADR-0074
#: §6). Every kind **except** ``EPISODIC``: the command answers "what do you
#: believe about me", and an episode is not a belief — it is the evidence a belief
#: is made of, so a kind-blind listing would print a transcript through the surface
#: leg 1 built to be readable. ``--kind episodic`` still lists them, and the store
#: contract is untouched: ADR-0073 §1's "``None`` means every value" is a *store*
#: semantic, and ADR-0073 never pinned this command's default.
#:
#: Derived rather than spelled out, so a fifth ``MemoryKind`` is listed by default
#: rather than silently omitted by a list nobody updated.
_DEFAULT_BELIEF_KINDS: tuple[MemoryKind, ...] = tuple(
    kind for kind in MemoryKind if kind is not MemoryKind.EPISODIC
)


def _present_source(value: str) -> str:
    r"""Reject a blank ``source`` during Typer's parameter parsing, **without stripping**.

    :func:`_present_content`'s shape, for the same reason and with one extra rule.
    The reason: ``NonBlankEncodableText`` refuses a blank value with a
    ``ValueError``, which is **not** an :class:`AssistantError`, so it would escape
    :func:`_revoke_source`'s and :func:`_grant_source`'s error boundaries as an
    uncaught traceback with no controlled exit code — the failure ADR-0042 §7
    forbids. Catching it here makes it a normal usage error (exit code 2) before
    any client is built.

    **Encodability is checked as well as blankness**, and it is a real case rather
    than a defensive one — the same mechanism ADR-0102 §6 names for a configured
    path, one argument over. Linux passes argv as bytes and Python decodes it with
    ``surrogateescape``, so ``assistant revoke $'\xe9'`` arrives as a lone surrogate
    that ``EncodableText`` refuses and ADR-0087's encoder cannot express. Without
    this the refusal lands in the client, as the same uncaught ``ValueError`` this
    callback exists to prevent.

    The extra rule is that **the value is returned byte for byte** (ADR-0102 §2).
    An adapter that stripped it would make ``revoke " calendar "`` reach the hub as
    ``calendar`` and *match* a held reader, where ADR-0097 §10 requires that a
    source differing from a declared name only by surrounding whitespace is refused
    rather than matched — the substitutability failure §2 refuses the ``Identifier``
    annotation for, arriving one layer further out instead.

    Args:
        value: The source name as the user typed it.

    Returns:
        The value, unchanged.

    Raises:
        BadParameter: If the value is blank, or has no UTF-8 encoding.
    """
    if not value.strip():
        msg = "must not be blank"
        raise typer.BadParameter(msg)
    try:
        encodable_text(value)
    except ValueError as exc:
        # The value is **not** echoed: it is a caller-supplied source, and it has no
        # UTF-8 encoding, so putting it in the message would be both an echo
        # ADR-0097 §9 forbids and a string this process may not be able to write
        # down. The remedy is the enumeration, not the value.
        msg = "must be text with a UTF-8 encoding; see 'assistant sources'"
        raise typer.BadParameter(msg) from exc
    return value


def _present_identity(value: str) -> str:
    r"""Reject a blank or unwritable account identity, **without stripping** it.

    :func:`_present_source`'s shape for the one argument on the connection surface
    that is :data:`~ai_assistant.core.types.NonBlankEncodableText` rather than
    :data:`~ai_assistant.core.types.Identifier`, and the non-stripping is
    contractual rather than incidental. ADR-0151 §5 forbids **every**
    implementation from stripping, case-folding, case-normalising or
    Unicode-normalising a caller-supplied identity "at any point — not at the
    surface", and a Typer callback that returned ``value.strip()`` would be the
    surface doing exactly that, one layer before the annotation ADR-0151 §2 chose
    ``NonBlankEncodableText`` over ``Identifier`` to prevent.

    The reason for a callback at all is :func:`_present_source`'s: the refusals
    below are ``ValueError``, which is **not** an :class:`AssistantError`, so they
    would escape :func:`_connect_account`'s error boundary as an uncaught traceback
    with no controlled exit code (ADR-0042 §7). Catching them here makes each a
    usage error (exit code 2) **before any client is built and before a credential
    is prompted for** — which is the ordering that matters on this surface, because
    the alternative asks a person for a secret in order to refuse the call anyway.

    **The value is never echoed**, and here that is a data-tier rule rather than a
    writability one: an account identity is Tier 1 personal data (ADR-0149 §3), so
    it reaches no log line, no error message and no operator diagnostic. Click
    renders a ``BadParameter`` as the parameter's name and this message, carrying
    neither.

    Args:
        value: The account identity as the user typed it.

    Returns:
        The value, byte for byte.

    Raises:
        BadParameter: If the value is blank, or has no UTF-8 encoding.
    """
    if not value.strip():
        msg = "must not be blank"
        raise typer.BadParameter(msg)
    try:
        encodable_text(value)
    except ValueError as exc:
        msg = "must be text with a UTF-8 encoding"
        raise typer.BadParameter(msg) from exc
    return value


def _distinct_scope(value: list[GrantScope]) -> list[GrantScope]:
    """Reject a repeated ``--scope`` during Typer's parameter parsing.

    ADR-0097 §10 spells a duplicated scope as a refusal rather than something to
    fold away silently — ``(FACET, FACET)`` is a caller that has lost track of what
    it is asking for — and both the client and the engine raise ``ValueError`` for
    it. That is not an :class:`AssistantError` either, so without this
    ``assistant grant calendar --scope facet --scope facet`` escapes as a traceback
    exactly as a blank source does.

    **Empty needs no check here**: the option is required, so Typer refuses a call
    that names no scope at all before this runs.

    Args:
        value: The scopes as the user repeated them.

    Returns:
        The value, unchanged — order is the record's validator's to normalise
        (ADR-0097 §10), not this adapter's.

    Raises:
        BadParameter: If a scope is named more than once.
    """
    if len(set(value)) != len(value):
        named = ", ".join(use.value for use in value)
        msg = f"names a use more than once ({named}); each may be given at most once"
        raise typer.BadParameter(msg)
    return value


#: ``assistant grant``'s repeatable scope flag, hoisted to module scope for the
#: reason the ``learn`` and ``beliefs`` enum options are (ruff's B008). Required
#: with no default, deliberately: ADR-0097 §2 refuses an empty scope at
#: construction, and a *default* scope would be this adapter deciding what a user
#: permitted — the one decision ADR-0097 §8 says nothing may make for them.
#:
#: **The help names every member of the enum, and ADR-0133 §6 forbids it naming
#: fewer.** The option is annotated ``list[GrantScope]``, so it accepts a new
#: member the instant it is declared; a help string still enumerating the older
#: uses would be "a surface disagreeing with the vocabulary", which is the failure
#: ADR-0097 §8 names when it forbids anything deciding what the user permitted on
#: their behalf. Suppressing a member here would take an added refusal that does
#: not exist, rather than saving one.
_GRANT_SCOPE_OPTION = typer.Option(
    ...,
    "--scope",
    callback=_distinct_scope,
    help=(
        "What this grant allows (repeatable): 'facet' to look at the source while "
        "answering, 'ingest' to durably remember what it says, 'notify' to read it "
        "in order to raise things with you unprompted."
    ),
)

#: The same option on ``amend``, and it carries **every** member for the same
#: reason (ADR-0139 §3's second clause, over ADR-0133 §6's): wherever a surface
#: offers, enumerates or explains the uses a user may choose among, it names all of
#: them. An amendment is a choice context, so nothing here may be trimmed on the
#: ground that the user granted a narrower set last time — that would be the
#: surface deciding what the user permits on their behalf.
_AMEND_SCOPE_OPTION = typer.Option(
    ...,
    "--scope",
    callback=_distinct_scope,
    help=(
        "What the *new* grant allows (repeatable), replacing the old one entirely: "
        "'facet' to look at the source while answering, 'ingest' to durably remember "
        "what it says, 'notify' to read it in order to raise things with you "
        "unprompted."
    ),
)


class _ActOutcome(Enum):
    """What a client can honestly say about one act of an amendment (ADR-0139 §4).

    **Three rather than two**, because a mutating call over a socket has a third
    and the corpus already knows it: a ``grant`` can be committed by the hub and
    lose its response (ADR-0085 §8e, #570), and ADR-0060 makes a cancelled write's
    effect indeterminate for the same reason. A two-outcome report forces a client
    in that state to assert one of two things it does not know.

    It reaches the **revocation** as well as the grant: the first act is a mutating
    call over the same socket and has no better guarantee than the second.
    """

    #: The hub answered, and the record is appended.
    LANDED = "landed"
    #: The hub answered with a refusal, so nothing was written.
    NOT_LANDED = "known not to have landed"
    #: The response was lost, the call was cancelled, or the result could not be
    #: returned after the work had committed. The hub may have done it.
    UNKNOWN = "not known"


@final
class _Unread:
    """A source whose current grant state this surface has **not** read.

    ADR-0139 §4's third clause gives a surface that has not read exactly one thing
    to say — that the state is unread — rather than a default to fall back on. It is
    a distinct value rather than ``None`` because ``None`` already means something
    here: read, and no grant covers the source. Collapsing the two would be the
    inference the clause forbids, wearing a type.
    """


#: The one instance; there is nothing to distinguish two of them.
_UNREAD = _Unread()


def _utcnow() -> datetime:
    """The wall-clock 'now' the ``learn`` command stamps on a ``FeedbackEvent``.

    The same module-level clock convention every subsystem uses
    (``datetime.now(UTC)``); ``FeedbackEvent.created_at`` is a
    :data:`~ai_assistant.core.types.UtcInstant`, so the reading is validated as
    timezone-aware UTC at construction. Named so a test can substitute it for a
    deterministic timestamp.
    """
    return datetime.now(UTC)


@app.callback()
def main() -> None:
    """Root command group. Keeps subcommands addressable by name.

    Deliberately does no configuration work: loading settings can fail, and a
    failure here would escape as an uncaught traceback with no controlled exit
    code. Each command that needs settings loads them inside its own error
    boundary instead (ADR-0042 §7), so a bad ``ASSISTANT_*`` value is rendered,
    not dumped.
    """


@app.command()
def version() -> None:
    """Print the installed version."""
    console.print(f"ai-assistant [bold cyan]{__version__}[/]")


@app.command()
def gateway() -> None:
    """Serve this device's browsers, and print the value one browser starts with.

    A **subcommand** rather than a console script of its own, and that inverts the
    standing instinct on purpose (ADR-0168 §1). ADR-0084 §6 gave the hub its own
    script because a subcommand would put it in ``interfaces``, "which would then
    have to import ``service``" — a rule about where code must live, and one that
    does not reach a gateway: an interface adapter belongs in ``interfaces``
    already, and this is the first time that rule has been examined and found not
    to fire.

    The gateway binds a loopback port on **this** machine and serves the browsers
    on it. It starts whether or not the hub is reachable, so that a browser
    reaching it learns the hub is down rather than that nothing is there
    (ADR-0168 §9), and every session ends when this process does (ADR-0168 §4).
    """
    raise typer.Exit(asyncio.run(_serve_gateway()))


def _positive_finite_seconds(value: float) -> float:
    """Reject a ``--timeout`` that is not a usable number of seconds.

    Runs during Typer's parameter parsing, so an invalid value is a normal usage
    error (exit code 2) rather than an ``OverflowError`` from ``timedelta`` or a
    non-positive budget the executor would later refuse mid-run. Rejected: a
    non-finite value (``inf``/``nan``), a non-positive one, and a finite value too
    large to be a ``timedelta`` (e.g. ``1e100``) — the last checked by constructing
    it here, so ``_ask`` can build the same duration without overflowing.
    """
    if not math.isfinite(value) or value <= 0:
        msg = "must be a positive, finite number of seconds"
        raise typer.BadParameter(msg)
    try:
        duration = timedelta(seconds=value)
    except OverflowError as exc:
        msg = "is too large to be a duration"
        raise typer.BadParameter(msg) from exc
    # A positive value below timedelta's microsecond resolution (e.g. 1e-7) rounds
    # to zero — a deadline the executor refuses. Reject it as invalid input, not a
    # mid-run ValueError.
    if duration <= timedelta(0):
        msg = "is too small to be a usable deadline"
        raise typer.BadParameter(msg)
    return value


def _present_content(value: str) -> str:
    """Reject blank ``learn`` content during Typer's parameter parsing.

    ``FeedbackEvent.content`` rejects whitespace-only text with a ``ValidationError``
    (``core/types.py``), which is **not** an :class:`AssistantError`, so constructing
    the event on blank input would escape both of :func:`_learn_feedback`'s error
    boundaries as an uncaught traceback with no controlled exit code — the failure
    ADR-0042 §7 forbids. Catching it here instead makes it a normal usage error
    (exit code 2), before any engine is built, mirroring :func:`_positive_finite_seconds`.
    The value is returned untouched; the event's own validator trims it.
    """
    if not value.strip():
        msg = "must not be blank"
        raise typer.BadParameter(msg)
    return value


def _present_subject(value: str | None) -> str | None:
    r"""Reject a blank ``--about-person`` during parsing, **without stripping**.

    The subject axis's route into ``FeedbackEvent`` (ADR-0100 §7), and it borrows
    :func:`_present_source`'s shape rather than :func:`_present_content`'s for the
    reason that separates them. ``FeedbackEvent.about_person`` is
    ``NonBlankEncodableText``, which refuses a blank value and an unencodable one
    with a ``ValidationError`` — **not** an :class:`AssistantError`, so
    constructing the event on either would escape :func:`_learn_feedback`'s error
    boundaries as an uncaught traceback with no controlled exit code, the failure
    ADR-0042 §7 forbids. Both cases are real: ``--about-person ""`` is a slip a
    shell makes easy, and Linux passes argv as bytes that Python decodes with
    ``surrogateescape``, so ``assistant learn x --about-person $'\xe9'`` arrives as
    a lone surrogate no UTF-8 encoder will accept.

    **The value is returned byte for byte** (ADR-0100 §6). An adapter that
    stripped it would store ``" Marta "`` as ``"Marta"``, and §6's third clause
    keeps a label exactly as the user gave it precisely so that every later
    matching rule stays available — none of them can be recovered from labels that
    were quietly normalised on the way in. The refusal is allowed to *strip in
    order to decide*; what it may not do is return the stripped value.

    ``None`` — the option not given — is the "no subject stated" state and passes
    through untouched, which is the one thing this callback must not turn into a
    blank.

    Args:
        value: The subject as the user typed it, or ``None`` when unset.

    Returns:
        The value, unchanged.

    Raises:
        BadParameter: If the value is blank, or has no UTF-8 encoding.
    """
    if value is None:
        return None
    if not value.strip():
        msg = "must not be blank"
        raise typer.BadParameter(msg)
    try:
        encodable_text(value)
    except ValueError as exc:
        # Not echoed, for :func:`_present_source`'s reason: a value with no UTF-8
        # encoding is one this process may not be able to write down, so reporting
        # the fault would fail the same way the fault does.
        msg = "must be text with a UTF-8 encoding"
        raise typer.BadParameter(msg) from exc
    return value


def _present_id(value: str) -> str:
    r"""Reject a blank or unwritable id during Typer's parameter parsing, **stripping** it.

    :func:`_present_source`'s shape with its normalisation rule inverted, and the
    inversion is the whole of why this is a separate function. The reason for having
    a callback at all is the same: ADR-0085 §3c puts
    :data:`~ai_assistant.core.types.Identifier` validation on *every* implementation
    of the engine surface, "before any I/O", and its refusal is a ``ValueError`` —
    **not** an :class:`AssistantError` and not a ``TransportError`` — so a blank id
    escapes each command's ``except (AssistantError, TransportError)`` boundary as an
    uncaught traceback with no controlled exit code, the failure ADR-0042 §7 forbids.
    Catching it here makes it a normal usage error (exit code 2) before any client is
    built, exactly as :func:`_page_argument` does for a page the store would refuse.

    **Encodability is checked as well as blankness**, and it is a real case rather
    than a defensive one. Linux passes argv as bytes and Python decodes it with
    ``surrogateescape``, so ``assistant forget $'\xe9'`` arrives as a lone surrogate
    that ``EncodableText`` refuses and ADR-0087's encoder cannot express; without this
    that refusal lands as the same uncaught ``ValueError`` a blank one does. The value
    is **not** echoed in the message, for :func:`_present_source`'s reason: a value
    with no UTF-8 encoding is one this process may not be able to write down, so
    reporting the fault would fail the same way the fault does.

    **The value is returned stripped**, where :func:`_present_source` returns its byte
    for byte, because the two arguments are refined by different types and the
    difference is decided rather than incidental. ADR-0085 §3c makes normalisation
    contractual for an *identity* argument — a rule that only rejected blanks "would
    leave stripping optional, and optional normalisation on an identity argument is
    worse than none: it makes the answer to ``belief(" rec-1 ")`` a property of which
    implementation you are holding". A grant's ``source`` is ``NonBlankEncodableText``
    instead, which ADR-0102 §2 keeps byte-exact so that a source differing from a
    declared name only by surrounding whitespace is refused rather than matched
    (ADR-0097 §10).

    Stripping *here* rather than leaving it to the implementation is not cosmetic
    either: the id this module keeps is the one :func:`_render_no_such_belief` and
    :func:`_render_no_such_conversation` report back, so without it a lookup the
    engine performed against ``rec-1`` would be reported against ``" rec-1 "``.

    Args:
        value: The identifier as the user typed it.

    Returns:
        The identifier stripped, which is what the engine is then asked about.

    Raises:
        BadParameter: If the value is blank, or has no UTF-8 encoding.
    """
    stripped = value.strip()
    if not stripped:
        msg = "must not be blank"
        raise typer.BadParameter(msg)
    try:
        encodable_text(stripped)
    except ValueError as exc:
        msg = "must be text with a UTF-8 encoding"
        raise typer.BadParameter(msg) from exc
    return stripped


def _present_optional_id(value: str | None) -> str | None:
    """:func:`_present_id` for the two id parameters that may be absent.

    ``observe``'s positional and ``ask --conversation`` both default to ``None``,
    which is the "no conversation named" state — the one thing this must not turn
    into a blank, and the reason it cannot simply be :func:`_present_id`. The shape
    :func:`_present_subject` uses for the same reason.

    Args:
        value: The identifier as the user typed it, or ``None`` when unset.

    Returns:
        The identifier stripped, or ``None``.

    Raises:
        BadParameter: If a value was given and is blank, or has no UTF-8 encoding.
    """
    return None if value is None else _present_id(value)


def _page_argument(value: int) -> int:
    """Reject a ``--limit``/``--offset`` the store would refuse (ADR-0073 §2).

    ``MemoryStore.list_beliefs`` raises ``ValueError`` for a paging argument outside
    ``[0, 2**63)`` — refused rather than clamped, because a negative one reaches
    SQLite as ``LIMIT -1`` (no limit at all) and an over-wide one raises
    ``OverflowError`` out of the driver. A ``ValueError`` is **not** an
    :class:`AssistantError`, so it would escape :func:`_list_beliefs`'s error
    boundary as an uncaught traceback with no controlled exit code — the failure
    ADR-0042 §7 forbids. Catching it during Typer's parameter parsing makes it a
    normal usage error (exit code 2) before any engine is built, exactly as
    :func:`_present_content` does for blank ``learn`` content.
    """
    if not 0 <= value < _PAGE_BOUND:
        msg = f"must be between 0 and {_PAGE_BOUND - 1}"
        raise typer.BadParameter(msg)
    return value


def _positive_page_argument(value: int) -> int:
    """Reject a ``--limit`` the grant store would refuse (ADR-0102 §10).

    :func:`_page_argument`'s stricter sibling, for the one paging argument on this
    surface whose floor is 1 rather than 0: ``SourceGrantStore.recent`` requires a
    strictly positive limit, and ADR-0102 §10 makes every implementation refuse a
    non-positive one locally. Caught during Typer's parameter parsing so it is a
    normal usage error (exit code 2) before any client is built, exactly as
    :func:`_page_argument` is.
    """
    if not 1 <= value < _PAGE_BOUND:
        msg = f"must be between 1 and {_PAGE_BOUND - 1}"
        raise typer.BadParameter(msg)
    return value


def _present_notification_class(value: str | None) -> str | None:
    """:func:`_present_source` for ``tune --class``: **byte-exact**, and that is the point.

    A notification class is ``NonBlankEncodableText``, the shape ADR-0102 §2 keeps
    byte-exact for a grant's ``source``, so the choice is made here rather than
    inherited — and it lands the same way, because the same substitutability failure
    is at the end of both roads.

    An earlier version of this stripped, reasoning that a class is matched against
    nothing: it *creates* a preference row, so a row written for ``" upcoming_event "``
    would govern nothing and normalising seemed the friendlier reading. That was
    wrong on the facts. ``NonBlankEncodableText`` preserves surrounding whitespace, so
    ``" upcoming_event "`` is an admissible class a producer may declare and a record
    may carry — and
    :meth:`~ai_assistant.core.types.NotificationPreferences.reach_for` compares
    exactly. Stripping therefore does not prevent the unreachable setting, it
    *guarantees* one for that class: whatever ``assistant notifications`` prints, this
    would write something else, and the class the user was looking at could not be
    tuned at all.

    Byte-exact makes the pasteable hint's round trip total instead: what the listing
    shows is what reaches ``ClassReach``. The cost is the other direction — a user who
    types a stray trailing space writes a row that governs nothing — which is
    ADR-0097 §10's accepted trade for ``source`` and is the recoverable half, because
    the class they meant is on screen.

    Args:
        value: The class as the user typed it, or ``None`` when unset.

    Returns:
        The value, unchanged.

    Raises:
        BadParameter: If a value was given and is blank, or has no UTF-8 encoding.
    """
    return None if value is None else _present_source(value)


def _quiet_window(spec: str) -> QuietWindow:
    """Parse one ``HH:MM-HH:MM`` quiet window into the engine's own value.

    Turning what the user typed into the request type is the adapter's own job
    (ADR-0042 §6, "Adaptation"), and it is *only* that: the endpoints go straight to
    :meth:`~ai_assistant.core.types.QuietWindow.between`, which owns the half-open
    convention, the wrap across midnight and the refusal of a window with no readable
    extent (ADR-0130 §6). Nothing here decides any of them.

    **The endpoints are naive local times and this refuses a zone**, by handing them
    to a constructor that does: quiet windows are read in ``Settings.timezone`` and
    ADR-0130 §6 introduces no second timezone source, so ``22:00+01:00`` is an error
    rather than a value quietly reinterpreted.

    **The grammar is enforced rather than merely documented, and the reason is the one
    input that would otherwise be accepted and changed.**
    :func:`~datetime.time.fromisoformat` is lenient enough to take ``22:00:59``, and
    :func:`~ai_assistant.core.types.minute_of_day` then *truncates* seconds — by
    design, since a window is a minute-resolution setting — so a user asking for
    ``22:00:59`` would be given ``22:00`` with nothing said. That is the failure
    :func:`_present_source` exists to prevent one argument over: a surface must not
    accept a value and then act on a different one. Anything but exactly ``HH:MM`` is
    refused, so the only values this takes are the ones it can hold.

    Args:
        spec: The window as the user typed it, e.g. ``22:00-07:00``.

    Returns:
        The window.

    Raises:
        ValueError: If the text is not two ``HH:MM`` endpoints separated by ``-``,
            if either carries a timezone or a finer precision than a minute, or if
            the two name the same minute.
    """
    start, separator, end = spec.partition("-")
    if not separator:
        msg = f"expected a window of the form HH:MM-HH:MM, got {spec!r}"
        raise ValueError(msg)
    endpoints = []
    for endpoint in (start, end):
        trimmed = endpoint.strip()
        if _HH_MM.fullmatch(trimmed) is None:
            msg = (
                f"each endpoint is exactly HH:MM, got {trimmed!r}: a quiet window is "
                f"held to the minute, so a finer one would be accepted and then "
                f"silently rounded down (ADR-0130 §6)"
            )
            raise ValueError(msg)
        endpoints.append(time.fromisoformat(trimmed))
    return QuietWindow.between(*endpoints)


def _present_quiet_windows(value: list[str] | None) -> list[str] | None:
    """Reject an unparseable ``--quiet-window`` during Typer's parameter parsing.

    :func:`_page_argument`'s shape and its reason exactly: every refusal
    :func:`_quiet_window` can hit is a ``ValueError`` — from
    :func:`~datetime.time.fromisoformat`, from
    :func:`~ai_assistant.core.types.minute_of_day`, or from ``QuietWindow``'s own
    validator — and a ``ValueError`` is **not** an :class:`AssistantError`, so it
    would escape :func:`_tune_notifications`'s error boundary as an uncaught
    traceback with no controlled exit code (ADR-0042 §7). Parsing here makes a
    mistyped window a normal usage error (exit code 2) before any client is built.

    The value is returned **unchanged** and parsed again where it is used: keeping
    the option's declared type ``list[str]`` is what lets one function be both the
    parser and the check, so the two can never disagree about what is admissible.

    Args:
        value: The windows as the user repeated them, or ``None`` when the flag was
            not given at all — which Typer supplies for an optional repeatable
            option and which is **not** the same as the empty set
            (``--no-quiet-windows`` is how that is said).

    Returns:
        The value, unchanged.

    Raises:
        BadParameter: If any window will not parse.
    """
    for spec in value or ():
        try:
            _quiet_window(spec)
        except ValueError as exc:
            raise typer.BadParameter(f"{spec!r}: {exc}") from exc
    return value


def _budget_argument(value: int | None) -> int | None:
    """Reject an ``--budget`` :class:`NotificationPreferences` would refuse.

    The field is ``0 <= budget < 2**63`` (ADR-0130 §6), and zero is a legible "never
    interrupt" rather than a defect, so the floor is 0 and not 1. Refused at parse
    time for :func:`_page_argument`'s reason: pydantic raises ``ValidationError``,
    which is not an :class:`AssistantError`, so it would escape the command's error
    boundary as a traceback.
    """
    if value is not None and not 0 <= value < _PAGE_BOUND:
        msg = f"must be between 0 and {_PAGE_BOUND - 1}"
        raise typer.BadParameter(msg)
    return value


#: ``assistant tune``'s reach flag, hoisted to module scope for the reason the
#: ``learn``, ``beliefs`` and ``grant`` enum options are (ruff's B008). Optional
#: rather than required: ``tune`` writes only the axes the user named, and reach is
#: one of three standing settings (ADR-0130 §6).
_TUNE_REACH_OPTION = typer.Option(
    None,
    "--reach",
    help=(
        "How far the class named by --class may reach you: 'off' never tells you, "
        "'hold' keeps it for when you next look (the default for every class), "
        "'interrupt' lets it reach you at the time."
    ),
)

#: ``assistant tune``'s repeatable quiet-window flag, hoisted for B008's reason — a
#: list-annotated option is no more exempt from it than an enum-annotated one.
#: Repeating it **replaces** the whole set, which is the one legible reading of a
#: repeated flag against a surface that writes the whole value (ADR-0130 §6).
_TUNE_QUIET_WINDOW_OPTION = typer.Option(
    None,
    "--quiet-window",
    callback=_present_quiet_windows,
    metavar="HH:MM-HH:MM",
    help=(
        "An interval of your local day during which nothing interrupts, e.g. "
        "'22:00-07:00' (it may cross midnight). Repeatable; giving any replaces the "
        "whole set. Use --no-quiet-windows to remove them all."
    ),
)


class _Tuning(NamedTuple):
    """What one ``assistant tune`` invocation was asked to change (ADR-0130 §6).

    A parcel rather than five parameters threaded through four functions, and it is
    the **parsed** form: :func:`_tuning` is where what the user typed becomes the
    value the engine's own type takes, so everything downstream of it relays rather
    than parses. ``None`` on an axis means "the user did not name this", which
    :func:`_tuned` reads as "write back what was already there" — the distinction
    that lets one act be performed without restating the other two.
    """

    notification_class: str | None
    reach: NotificationReach | None
    quiet_windows: tuple[QuietWindow, ...]
    clear_quiet_windows: bool
    budget: int | None


def _tuning(
    *,
    notification_class: str | None,
    reach: NotificationReach | None,
    quiet_windows: list[str],
    clear_quiet_windows: bool,
    budget: int | None,
) -> _Tuning:
    """Check the flags agree with each other and parse them (ADR-0042 §6, §7).

    Three refusals live here rather than behind the engine call, because all three are
    decidable from what was typed and none should cost a round trip — and because a
    usage error belongs at parse time, where it is exit code 2 rather than an
    :class:`AssistantError` rendered from inside a session:

    * **``--class`` and ``--reach`` are one setting and are given together.** Either
      alone names half of "this class may reach me this far", and supplying the other
      half would be this adapter deciding what the user permitted.
    * **``--quiet-window`` and ``--no-quiet-windows`` contradict each other**, so the
      pair is refused rather than resolved by precedence. A precedence rule is a
      decision the user cannot see in what they typed.
    * **A call naming nothing at all is refused**, because the write is not a no-op:
      ADR-0130 §6 has it stamp a reconsideration instant onto the records the change
      reaches, so "write back exactly what I read" would re-arm held notifications
      with nothing to show for it.

    Args:
        notification_class: ``--class``, already stripped and non-blank, or ``None``.
        reach: ``--reach``, or ``None``.
        quiet_windows: ``--quiet-window``, each already known to parse.
        clear_quiet_windows: Whether ``--no-quiet-windows`` was given.
        budget: ``--budget``, already known to be in range, or ``None``.

    Returns:
        The parsed request.

    Raises:
        BadParameter: If the flags contradict each other or name nothing.
    """
    if (notification_class is None) != (reach is None):
        msg = "--class and --reach set one class's reach and are given together"
        raise typer.BadParameter(msg)
    if quiet_windows and clear_quiet_windows:
        msg = "--quiet-window and --no-quiet-windows contradict each other; give one"
        raise typer.BadParameter(msg)
    if (
        notification_class is None
        and not quiet_windows
        and not clear_quiet_windows
        and budget is None
    ):
        msg = (
            "names nothing to change; give --class with --reach, --quiet-window, "
            "--no-quiet-windows or --budget"
        )
        raise typer.BadParameter(msg)
    return _Tuning(
        notification_class=notification_class,
        reach=reach,
        # Parsed here and not in the callback: keeping the option's declared type
        # ``list[str]`` is what lets one function be both the parser and the
        # parse-time check, so the two can never disagree about what is admissible.
        quiet_windows=tuple(_quiet_window(spec) for spec in quiet_windows),
        clear_quiet_windows=clear_quiet_windows,
        budget=budget,
    )


@app.command()
def ask(
    utterance: str = typer.Argument(..., help="What you want the assistant to do."),
    timeout_seconds: float = typer.Option(
        60.0,
        "--timeout",
        callback=_positive_finite_seconds,
        help="Per-attempt deadline for the engine's work, in seconds (positive).",
    ),
    conversation: str | None = typer.Option(
        None,
        "--conversation",
        "-c",
        callback=_present_optional_id,
        help=(
            "Continue this conversation (see 'assistant conversations'). "
            "Omit it to start a new one; the id is printed either way."
        ),
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve any confirmation without prompting."
    ),
) -> None:
    """Run one turn: plan it, drive its step, and render what happened.

    Every turn runs under a conversation, and the id it ran under is printed so you
    can continue it with ``--conversation``. Passing an id the assistant does not
    know is an error rather than a fresh start — a typo must not quietly land your
    continuation somewhere you cannot find it.

    If the engine parks a step for confirmation, the prompt shows the action and
    the policy's reason; answering relays the opaque token back to the engine.
    """
    code = asyncio.run(
        _ask(
            utterance,
            timeout_seconds=timeout_seconds,
            assume_yes=yes,
            conversation_id=conversation,
        )
    )
    raise typer.Exit(code)


@app.command()
def conversations(
    limit: int = typer.Option(
        50, "--limit", callback=_page_argument, help="How many conversations to show at most."
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many conversations to skip before the page begins.",
    ),
) -> None:
    """List your recent conversations, most recently active first.

    Each row shows the id ``assistant ask --conversation`` takes, when the
    conversation started, and when it was last active. A conversation you deleted is
    not listed, and neither is one whose record retention has already reclaimed.

    There is no total count — ask for the next page to find out whether there is
    more.
    """
    code = asyncio.run(_list_conversations(limit=limit, offset=offset))
    raise typer.Exit(code)


@app.command("forget-conversation")
def forget_conversation(
    conversation_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the conversation to destroy."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The conversation is still shown first."
    ),
) -> None:
    """Destroy one conversation and everything it recorded, after showing you what.

    You are shown how many turns it holds and when it ran — the count and span
    rather than every turn, which is what a person can actually judge at a prompt —
    and it is destroyed only once you agree. ``--yes`` skips the question, not the
    rendering.

    This destroys: the conversation's episodes are gone from memory, from
    ``assistant beliefs`` and from any export. Turns already deleted or expired stay
    gone; nothing is restored.
    """
    code = asyncio.run(_forget_conversation(conversation_id, assume_yes=yes))
    raise typer.Exit(code)


@transcript_app.command("search")
def transcript_search(
    query: str = typer.Argument(
        ..., callback=_present_content, help="The words to look for, as you would say them."
    ),
    limit: int = typer.Option(
        50, "--limit", callback=_positive_page_argument, help="How many hits to show at most."
    ),
    offset: int = typer.Option(
        0, "--offset", callback=_page_argument, help="How many hits to skip before the page begins."
    ),
) -> None:
    """Find where you or I said something, newest first.

    A plain substring match, case-insensitive, over each half of a turn separately —
    no stemming, no synonyms, no fuzzy matching, and nothing clever about meaning.
    A query spanning the join between what you said and what I said matches nothing,
    because the two halves are searched apart.

    Each hit shows a bounded taste of the matching text and the address to read the
    turn whole by: ``assistant transcript show <address>``.
    """
    code = asyncio.run(_search_transcript(query, limit=limit, offset=offset))
    raise typer.Exit(code)


@transcript_app.command("conversation")
def transcript_conversation(
    conversation_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the conversation to read."
    ),
    limit: int = typer.Option(
        50, "--limit", callback=_positive_page_argument, help="How many turns to show at most."
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many turns to skip before the page begins.",
    ),
) -> None:
    """Read one conversation's transcript, in the order it was said.

    **This works after the conversation itself is gone.** A conversation whose turns
    have passed their retention window is reclaimed — ``assistant conversations`` no
    longer lists it and ``assistant forget-conversation`` no longer knows it — and the
    transcript is still here. That is what the archive is for.
    """
    code = asyncio.run(_read_transcript_conversation(conversation_id, limit=limit, offset=offset))
    raise typer.Exit(code)


@transcript_app.command("show")
def transcript_show(
    address: str = typer.Argument(
        ..., callback=_present_id, help="The address of the turn to read, from a search hit."
    ),
) -> None:
    """Read one turn whole — both halves, nothing elided.

    The address comes from ``assistant transcript search`` or from
    ``assistant transcript conversation``. It is stable: it goes on naming this turn
    after the turn itself has left memory.
    """
    code = asyncio.run(_read_transcript_entry(address))
    raise typer.Exit(code)


@transcript_app.command("export")
def transcript_export(
    limit: int = typer.Option(
        50, "--limit", callback=_positive_page_argument, help="How many turns to show at most."
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many turns to skip before the page begins.",
    ),
) -> None:
    """Read every turn the archive holds, newest first — this is the export.

    A paged, ordered, unfiltered read of everything held. For a store that holds text
    and nothing else that *is* the portable snapshot, so there is no second format to
    ask for: page through this and you have all of it.
    """
    code = asyncio.run(_export_transcript(limit=limit, offset=offset))
    raise typer.Exit(code)


@transcript_app.command("forget")
def transcript_forget(
    address: str = typer.Argument(
        ..., callback=_present_id, help="The address of the turn to destroy."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The turn is still shown first."
    ),
) -> None:
    """Destroy one turn's transcript, after showing you what it says.

    This destroys the *transcript* and nothing else: what I believe is untouched, and
    ``assistant forget`` is the command for that. It reaches a turn a retention window
    is already hiding, so an address a read answers nothing for can still be destroyed
    here.
    """
    code = asyncio.run(_forget_transcript_entry(address, assume_yes=yes))
    raise typer.Exit(code)


@transcript_app.command("forget-conversation")
def transcript_forget_conversation(
    conversation_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the conversation whose transcript to destroy."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. What is held is still shown first."
    ),
) -> None:
    """Destroy one conversation's whole transcript, after showing you what is held.

    You are shown what is readable under that id before you answer, and told that the
    destruction reaches every turn of the conversation — including any this page did
    not show and any a retention window is hiding. ``--yes`` skips the question, not
    the rendering.

    This destroys the *transcript*. ``assistant forget-conversation`` is the command
    that destroys the conversation and its episodes; this one reaches a conversation
    that command no longer knows.
    """
    code = asyncio.run(_forget_transcript_conversation(conversation_id, assume_yes=yes))
    raise typer.Exit(code)


@app.command()
def resume(
    timeout_seconds: float = typer.Option(
        60.0,
        "--timeout",
        callback=_positive_finite_seconds,
        help="Per-attempt deadline for the engine's work, in seconds (positive).",
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve every pending confirmation without prompting."
    ),
) -> None:
    """Answer confirmations parked by an earlier run — including across a restart.

    A confirmable action from a previous ``ask`` may still be awaiting an answer: it
    was parked durably (ADR-0052) and survives a process exit. This reconstructs
    each such confirmation from stored state, shows the action and the policy's
    reason, and relays the opaque token back to the engine to resolve it.
    """
    code = asyncio.run(_resume_pending(timeout_seconds=timeout_seconds, assume_yes=yes))
    raise typer.Exit(code)


@app.command()
def learn(  # noqa: PLR0913 — the content plus one flag per axis of the event: two kinds, two subjects, and who may receive it
    content: str = typer.Argument(
        ..., help="The correction or preference, in your own words.", callback=_present_content
    ),
    kind: FeedbackKind = _LEARN_KIND_OPTION,
    about: str | None = typer.Option(
        None, "--about", "-a", help="Optional scope this feedback is about, e.g. 'units'."
    ),
    about_person: str | None = typer.Option(
        None,
        "--about-person",
        callback=_present_subject,
        help=(
            "Whom this is about, if it is about someone other than you, e.g. 'Marta'. "
            "A name as you write it; nothing looks it up. Leave it off for anything "
            "about you or your world."
        ),
    ),
    memory_kind: MemoryKind | None = _LEARN_MEMORY_KIND_OPTION,
    *,
    guarded: bool = typer.Option(
        False,
        "--guarded",
        help=(
            "Keep what this establishes for you alone: I will not say it on a channel "
            "anyone else may hear. There is no flag for the opposite — leaving it off "
            "is not a decision either way."
        ),
    ),
) -> None:
    """Teach the assistant from a correction or a stated preference.

    Turns what you say into a ``FeedbackEvent`` and hands it to the engine, which
    folds it into long-term memory. The result is a short summary of what memory did
    with it — stored, reinforced, or superseded.

    **``--memory-kind`` says which drawer, and says "do not look"** (ADR-0122 §6).
    Give it and it is honoured unchanged, and the engine issues no lookup. Leave it
    off and ``--kind preference`` still means a preference — a stated preference
    establishes one by its own intent — while ``--kind correction`` leaves the
    drawer for the engine to resolve from the belief you are correcting, which is
    the only place that fact lives.

    **``--about`` and ``--about-person`` are two different things** (ADR-0100 §7).
    ``--about`` scopes a preference to a topic — ``--about 'email tone'``.
    ``--about-person`` says whom the belief is about, and it is the only way a
    belief about someone else can say so: without it ``assistant learn "Marta
    prefers window seats"`` is stored with no subject, which the system reads as
    *yours*. The person flag is spelled long because ``--about`` and ``-a`` were
    already the scope axis's, on this very command.

    **``--guarded`` says who may receive what this establishes, and it only ever
    narrows** (ADR-0217 §7). Given, every record this feedback produces is placed
    for you alone, so it is not said on a channel of unbounded audience; it is your
    own act and no later model proposal lifts it. There is deliberately **no
    ``--no-guarded``**: ADR-0217 adds a narrowing act at write and no widening one,
    and leaving the flag off is not an act of any kind — it leaves the record with
    the placement its class already has, which is not a record that you considered
    this belief and declined to guard it. To widen one later, or to guard a belief
    you have already told me, is a separate act on a stored record and not this
    command's (§7, deferred to its own lane).

    The flag is carried onto the event and nothing here reads it: deciding a
    record's placement is not adapter work (``CLAUDE.md``, "Interface adapters are
    thin"), so this sets a field and ``learning`` acts on it.
    """
    # `.get`, not `[...]`: `_DEFAULT_MEMORY_KIND` is deliberately not exhaustive, and
    # a miss is the absent value ADR-0122 §2 requires rather than a lookup error.
    declared_memory_kind = (
        memory_kind if memory_kind is not None else _DEFAULT_MEMORY_KIND.get(kind)
    )
    code = asyncio.run(
        _learn_feedback(
            content,
            kind=kind,
            memory_kind=declared_memory_kind,
            subject=about,
            about_person=about_person,
            guarded=guarded,
        )
    )
    raise typer.Exit(code)


@app.command()
def beliefs(
    band: list[BeliefBand] | None = _BELIEFS_BAND_OPTION,
    kind: list[MemoryKind] | None = _BELIEFS_KIND_OPTION,
    limit: int = typer.Option(
        50,
        "--limit",
        callback=_page_argument,
        help="How many beliefs to show at most.",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many beliefs to skip before the page begins.",
    ),
) -> None:
    """List what the assistant currently believes about you, newest revision first.

    Each belief is shown with the band it is held in, how strongly, why it is held,
    and the id ``assistant forget`` takes. Only *live* beliefs are listed: one the
    assistant has since revised is history, not a belief it holds, and it is
    reachable through a data export rather than here.

    There is no total count — ask for the next page to find out whether there is
    more.
    """
    # An absent repeatable flag arrives as an empty list, which the façade would read
    # as "select nothing" — the deliberate meaning of an *explicitly* empty filter
    # (ADR-0073 §1). A CLI has no way to say that and no reason to, so absent and
    # empty both become "every band" for --band. For --kind they become every kind
    # *except* episodic (ADR-0074 §6): this command answers "what do you believe
    # about me", and a kind-blind listing would print a transcript once capture is
    # writing turns. `--kind episodic` still lists them.
    code = asyncio.run(
        _list_beliefs(
            bands=band or None,
            kinds=list(kind) if kind else list(_DEFAULT_BELIEF_KINDS),
            limit=limit,
            offset=offset,
        )
    )
    raise typer.Exit(code)


@app.command()
def questions(
    limit: int = typer.Option(
        50, "--limit", callback=_page_argument, help="How many questions to show at most."
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many questions to skip before the page begins.",
    ),
) -> None:
    """List the questions I need you to answer before I change what I believe.

    Some corrections cannot be applied without your word — most often because what
    you told me contradicts something you told me earlier, and I may not quietly
    throw either away. Each question shows what accepting it would have me believe,
    why I am asking, and exactly what accepting would retire. Answer one with
    ``assistant answer``.

    A second list follows it where relevant: questions whose answer was **begun and
    whose outcome was never recorded**, because a process died part-way. I do not
    know whether those writes landed, so there is nothing to retry — each one says
    what to do instead.

    There is no total count — ask for the next page to find out whether there is
    more.
    """
    code = asyncio.run(_list_questions(limit=limit, offset=offset))
    raise typer.Exit(code)


@app.command()
def answer(
    question_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the question to answer."
    ),
    *,
    accept: bool = typer.Option(
        ...,
        "--accept/--reject",
        help="Whether to accept the proposed change (--accept) or decline it (--reject).",
    ),
) -> None:
    """Answer one deferred question — accept the change, or decline it.

    Accepting re-submits the proposal through the same gate ``assistant learn`` uses,
    now carrying your authority for exactly what the question showed you: it may
    retire an earlier thing you told me, and it may retire nothing else.

    Declining writes nothing and is remembered, so the same question is not put to
    you again. To change your mind later, forget the question
    (``assistant forget-question``) and teach me the correction again.

    The answer is binary on purpose. To say something different from either option,
    use ``assistant learn`` — that is a new correction, not an answer to this one.
    """
    code = asyncio.run(_answer_question(question_id, accept=accept))
    raise typer.Exit(code)


@app.command("forget-question")
def forget_question(
    question_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the question to destroy."
    ),
) -> None:
    """Destroy one deferred question, answered or not.

    Use this to dispose of a question whose answer was interrupted — it is the first
    of the two recovery steps ``assistant questions`` prints, and it is what frees me
    to ask again about the same thing. Use it too to be re-asked something you
    declined earlier.

    This destroys the question and the words it holds; it does **not** undo any
    memory write an interrupted answer may already have made. Check with
    ``assistant beliefs`` afterwards and use ``assistant learn`` if the correction is
    missing.
    """
    code = asyncio.run(_forget_question(question_id))
    raise typer.Exit(code)


@app.command()
def observe(
    conversation_id: str | None = typer.Argument(
        None,
        callback=_present_optional_id,
        help=(
            "The conversation to observe. Defaults to the least recently active "
            "conversation that still has turns nobody has distilled."
        ),
    ),
) -> None:
    """Distil beliefs from a conversation's recent turns, and record what stuck.

    The assistant reads back what was actually said, proposes what it should
    durably believe about you as a result, and puts each proposal through the same
    gate ``assistant learn`` uses — so nothing is stored just because a model
    suggested it. What comes back names the model route that read the transcript,
    every belief proposed and what became of it, and anything thrown away.

    Nothing observes on its own: this runs only when you ask for it. Whatever is
    stored is immediately visible with ``assistant beliefs`` and destroyable with
    ``assistant forget``.
    """
    code = asyncio.run(_observe_conversation(conversation_id))
    raise typer.Exit(code)


@app.command()
def forget(
    belief_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the belief to destroy."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The belief is still shown first."
    ),
) -> None:
    """Destroy one belief, after showing you what it is.

    The belief is rendered — with what forgetting it costs, which differs by band —
    and destroyed only once you agree. ``--yes`` skips the question, not the
    rendering.

    Forgetting **destroys**: nothing is kept, not even in an export. To fix a belief
    rather than lose it, use ``assistant learn --kind correction``, which retires the
    old belief and keeps it on the record.
    """
    code = asyncio.run(_forget_belief(belief_id, assume_yes=yes))
    raise typer.Exit(code)


@app.command()
def sources() -> None:
    """List the sources you can connect me to, and say which are connected.

    Each line names a source, where it currently reads from, and whether you have
    granted it — and for what. Nothing here reads any of those sources; this is the
    list of what you *could* let me read.

    You can only grant a source that appears here. There is deliberately no way to
    type a path: what may be granted is the set of sources this installation was
    built with, so a typo cannot become a permission.
    """
    code = asyncio.run(_list_sources())
    raise typer.Exit(code)


@app.command()
def grant(
    source: str = typer.Argument(
        ...,
        callback=_present_source,
        help="The source to connect (see 'assistant sources').",
    ),
    scope: list[GrantScope] = _GRANT_SCOPE_OPTION,
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the question. The source is still shown first."
    ),
) -> None:
    """Let me read one source, for the uses you name.

    I show you the source and **where it reads from** before asking, because a
    permission you were not shown is not one you gave. ``--yes`` supplies the
    answer; it never skips the rendering.

    ``--scope facet`` lets me look at the source to answer what you are asking right
    now, and remember nothing from it. ``--scope ingest`` lets me durably believe
    what it says. ``--scope notify`` lets me read it in order to raise things with
    you unprompted — it is permission to *read*, not a promise that anything
    arrives. They are separate on purpose — "read my calendar and remember it, but
    do not raise it with me unprompted" is a thing people mean. Name as many as you
    mean; naming one allows only that one.

    A source can have one grant at a time. To change what a grant covers, use
    'assistant amend' — or revoke and grant yourself; both acts stay on the record
    either way.
    """
    code = asyncio.run(_grant_source(source, scope=scope, assume_yes=yes))
    raise typer.Exit(code)


@app.command()
def amend(
    source: str = typer.Argument(
        ...,
        callback=_present_source,
        help="The source whose grant you want to change (see 'assistant granted').",
    ),
    scope: list[GrantScope] = _AMEND_SCOPE_OPTION,
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the question. The source is still shown first."
    ),
) -> None:
    """Change what one source's grant covers, by withdrawing it and granting anew.

    **This is two acts and I will tell you how each one went.** There is no way to
    change a grant in place: the record says what you actually decided, so a
    narrowing is a withdrawal followed by a new grant, and both stay on the record.
    Between them there is a moment when the source is granted for nothing — that
    moment cannot be closed, so what this does instead is never leave you guessing
    which half happened.

    Each act comes back as one of exactly three things: it **landed**, it is
    **known not to have landed**, or its outcome is **not known** — the last one
    because a call can be committed here and lose its answer on the way back to
    you. If the withdrawal's outcome is not known I send no grant at all, because
    guessing from what a second act returned is exactly the guess this exists to
    avoid.

    You give me the new scope up front, and I show you the source and where it
    reads from before I touch anything — the same disclosure 'assistant grant'
    makes, because the granting half of an amendment is a grant like any other.
    Nothing is withdrawn in order to ask you a question.
    """
    code = asyncio.run(_amend_source(source, scope=scope, assume_yes=yes))
    raise typer.Exit(code)


@app.command()
def revoke(
    source: str = typer.Argument(..., callback=_present_source, help="The source to disconnect."),
) -> None:
    """Stop me reading one source, from now on.

    **No question is asked and nothing stands in the way**, deliberately: this is
    your remedy, and a prompt between you and it is a prompt too many. It works even
    for a source that is no longer configured, which is exactly when you would
    otherwise be stuck.

    What this does **not** do: it retires nothing I already believe, and it does not
    stop a read that is already running — it stops the next one from starting, and
    nothing a running read produces is used. Use ``assistant beliefs`` and
    ``assistant forget`` for what I already hold.
    """
    code = asyncio.run(_revoke_source(source))
    raise typer.Exit(code)


@app.command()
def grants(
    limit: int = typer.Option(
        50,
        "--limit",
        callback=_positive_page_argument,
        help="How many records to show at most (at least 1).",
    ),
) -> None:
    """Show what you granted and what you withdrew, most recent first.

    Both kinds of act are here, and nothing is ever edited or removed from this
    list: withdrawing a grant adds a record, it does not delete one. That is what
    makes this the honest answer to "what have I permitted, and when".

    **Do not read liveness off this list.** A record here says an act happened, not
    that it still stands — use ``assistant granted``, which asks me directly.
    """
    code = asyncio.run(_list_grants(limit=limit))
    raise typer.Exit(code)


@app.command()
def granted() -> None:
    """Show every source I am currently allowed to read, and for what.

    This is the honest answer to "what have I permitted": it comes from the record
    of what you decided, not from what happens to be plugged in today. So a source
    you granted and then unconfigured is **still listed here**, which is the point
    — it is still permitted, and this is where you find its name in order to
    withdraw it.

    It is a different question from 'assistant sources', which lists what you
    *could* connect me to. The two can disagree and that is not a fault: something
    can be available and ungranted, or granted and no longer available. Neither
    list is derived from the other, and neither answers the other's question.

    It also says nothing about *reading*. A grant is what you allowed; whether
    anything was actually read is a question nothing here answers yet.
    """
    code = asyncio.run(_list_standing())
    raise typer.Exit(code)


@app.command()
def notifications(
    limit: int = typer.Option(
        50, "--limit", callback=_page_argument, help="How many notifications to show at most."
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        callback=_page_argument,
        help="How many notifications to skip before the page begins.",
    ),
) -> None:
    """List what I am holding to tell you, oldest first.

    This is the only way a held notification reaches you: nothing is folded into an
    answer you did not ask for, and no count of them appears on an ordinary turn.

    Each row shows what I would tell you, the class it belongs to — which is what
    ``assistant tune`` takes — the ruling I made and what it is waiting on, and the
    ids that ``assistant dismiss`` and ``assistant forget-notification`` take. One
    whose moment has passed is still listed and still says when it expired; expiry
    ends it, it does not delete it.

    There is no total count — ask for the next page to find out whether there is
    more.
    """
    code = asyncio.run(_list_notifications(limit=limit, offset=offset))
    raise typer.Exit(code)


@app.command()
def dismiss(
    notification_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the notification to dismiss."
    ),
) -> None:
    """Deal with one notification, without destroying it.

    Dismissing ends it: it stops counting against how many I may hold, and it stops
    suppressing the same observation — so if that fact comes up again it is a fresh
    notification rather than a duplicate I quietly swallow.

    **It is not a deletion.** The record stays readable and stays in your export; use
    ``assistant forget-notification`` to destroy it. To stop a whole class reaching
    you rather than one item, use ``assistant tune --class ... --reach off``.
    """
    code = asyncio.run(_dismiss_notification(notification_id))
    raise typer.Exit(code)


@app.command("forget-notification")
def forget_notification(
    notification_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the notification to destroy."
    ),
) -> None:
    """Destroy one notification, so the same thing can be raised again.

    This removes the record and the words it holds — from the listing and from any
    export. Because the record is also what stops the same observation being raised
    twice, destroying it means the next time I notice that fact it is new to me.

    To deal with a notification while keeping the record, use ``assistant dismiss``.
    """
    code = asyncio.run(_forget_notification(notification_id))
    raise typer.Exit(code)


@app.command("notification-settings")
def notification_settings() -> None:
    """Show what you have decided may reach you unprompted, and how often.

    Three standing settings: how far each notification class may reach you, the hours
    during which nothing interrupts, and how many interruptions I may make in a
    rolling window. Every one of them has a shipped default, so this answers on the
    first day from an empty store — and the default reach is **hold** for every
    class, which is why nothing interrupts until you say it may.

    Change any of them with ``assistant tune``.
    """
    code = asyncio.run(_show_notification_settings())
    raise typer.Exit(code)


@app.command()
def tune(
    notification_class: str | None = typer.Option(
        None,
        "--class",
        callback=_present_notification_class,
        help=(
            "The notification class to set the reach of, as 'assistant notifications' "
            "prints it beside each record. Give it with --reach."
        ),
    ),
    reach: NotificationReach | None = _TUNE_REACH_OPTION,
    quiet_window: list[str] | None = _TUNE_QUIET_WINDOW_OPTION,
    budget: int | None = typer.Option(
        None,
        "--budget",
        callback=_budget_argument,
        help="How many times I may interrupt you per rolling window. 0 means never.",
    ),
    *,
    clear_quiet_windows: bool = typer.Option(
        False, "--no-quiet-windows", help="Remove every quiet window, so no hour is quiet."
    ),
) -> None:
    """Tune what may reach you unprompted — reach, quiet hours, and how often.

    Out of the box **nothing interrupts**: every class is held for when
    you next look, deliberately, so nothing I have just learned to notice
    can interrupt you before you have said it may. Raising a class is
    that act, and it is the only thing that makes an interruption
    possible at all.

    Only what you name is changed; the rest is read and written back
    untouched. If something else changes these at the same moment, the
    last write wins.

    Raising a class also reaches what I am **already** holding of it, so
    a notification that has been sitting there can reach you once you
    allow it. Setting a class to ``off`` likewise reaches what is already
    held — "never tell me this" is about what is waiting as well as what
    comes next — and it recalls nothing already sent.

    **Three separate acts arm unprompted contact, and none implies
    another.** For the calendar's upcoming events they are:

    1. The operator arms the producer, in the hub's environment:
       ASSISTANT_CALENDAR_UPCOMING_INTERVAL, an ISO-8601 duration.
       'PT15M' is fifteen minutes and 'PT30S' thirty seconds; a bare
       number such as '15' is refused.
    2. You grant the read: 'assistant grant calendar --scope notify'.
       The source is positional — there is no --source option. See
       'assistant sources' for what this installation offers.
    3. You raise the class, here:
       'assistant tune --class upcoming_event --reach interrupt'.
       Every deployment's classes are whatever its producers declare;
       'assistant notifications' prints each record's own class.
    """
    asked = _tuning(
        notification_class=notification_class,
        reach=reach,
        quiet_windows=quiet_window or [],
        clear_quiet_windows=clear_quiet_windows,
        budget=budget,
    )
    code = asyncio.run(_tune_notifications(asked))
    raise typer.Exit(code)


# --- the connection surface (ADR-0151 §1, §16) -------------------------------
# The five operations by which a person connects an account to a service, replaces
# its credential, disconnects it, sees what is connected, and reads back what was
# done. Four clauses here are the *client's* and are unenforceable from the hub's
# side (ADR-0098 §5): §5's display of the identity, §4's rendering of a PENDING
# record, §7's report of a partial outcome, and §8's two clauses about what a
# disconnection may be said to have done. This is the only place they can live.
#
# **The spellings are this lane's under ADR-0073 §1**, taken from ADR-0151 §16's
# illustrative list. `connect` is deliberately not a near-neighbour of `grant`:
# ADR-0151 §12 forbids offering a connection as an alternative to a grant, so each
# command below says which question it does *not* answer.


#: The scriptable door onto the credential, shared by ``connect`` and
#: ``reconnect``. Hoisted for ruff's B008 like the other shared options.
#:
#: **There is deliberately no ``--credential`` option.** A secret on the command
#: line lands in the shell's history file, in every ``ps`` listing while the
#: process runs, and in any log that records an invocation — three durable
#: disclosures of a Tier 0 value (ADR-0125 §1) that no amount of care downstream
#: undoes. ``device enrol`` reads its credential the same way and for the same
#: reason.
_CREDENTIAL_STDIN_OPTION = typer.Option(
    False,
    "--credential-stdin",
    help="Read the credential from the first line of standard input instead of prompting.",
)


@app.command()
def connect(
    identity: str = typer.Argument(
        ...,
        metavar="IDENTITY",
        callback=_present_identity,
        help="The account's name at the service, as you recognise it — an address or a handle.",
    ),
    *,
    credential_stdin: bool = _CREDENTIAL_STDIN_OPTION,
) -> None:
    """Connect an account, under a reference I mint.

    I show you the identity you typed and then ask for the credential, which is
    **never** an argument: a secret on the command line is in your shell history
    and in every process listing for as long as the call runs. Use
    ``--credential-stdin`` to pipe it in instead.

    **You cannot name the connection and I will not let you try.** The reference is
    minted here, at the moment the first record is written, because it is the one
    handle on this surface that may be logged — and a value you typed could not be
    (ADR-0149 §3). So every act after this one goes through
    ``assistant connections``, which is where you read the reference back.

    Showing you the identity is part of the act rather than a courtesy: the
    commonest way to leak a credential on a surface like this is to paste it into
    the name field, and seeing it is what catches that.

    **This is not 'assistant grant'.** A connection is not permission to act, it
    authorises nothing, and it never appears in what I am allowed to read.
    """
    code = asyncio.run(_connect_account(identity, credential_stdin=credential_stdin))
    raise typer.Exit(code)


@app.command()
def reconnect(
    reference: str = typer.Argument(
        ...,
        metavar="REFERENCE",
        callback=_present_id,
        help="The connection to re-provision, as 'assistant connections' prints it.",
    ),
    identity: str = typer.Option(
        ...,
        "--identity",
        callback=_present_identity,
        help="The account identity for the new revision. Shown back to you before I ask.",
    ),
    *,
    credential_stdin: bool = _CREDENTIAL_STDIN_OPTION,
) -> None:
    """Replace the credential under a connection you already have.

    This is the act for a rotated token. It keeps the reference — that is what
    makes the reference worth having — and takes the connection to a new revision;
    the credential it replaces is deleted once the new one is in use.

    **It is a different command from ``assistant connect`` on purpose.** Connecting
    cannot be aimed at a connection that exists, and re-provisioning refuses a
    reference I do not hold, so the mistake of meaning to replace a credential and
    creating a second connection instead is unreachable rather than merely visible.

    The reference is positional and the identity is a named option, so the two
    cannot be transposed. As on ``connect``, the credential is prompted for and is
    never an argument.
    """
    code = asyncio.run(
        _reprovision_account(reference, identity=identity, credential_stdin=credential_stdin)
    )
    raise typer.Exit(code)


@app.command()
def disconnect(
    reference: str = typer.Argument(
        ...,
        metavar="REFERENCE",
        callback=_present_id,
        help="The connection to disconnect, as 'assistant connections' prints it.",
    ),
) -> None:
    """Disconnect one account and delete the credentials it left behind.

    **No question is asked**, for the reason ``assistant revoke`` asks none: this is
    your remedy, and a prompt between you and it is a prompt too many at the moment
    you have decided a credential should stop working. It is idempotent — running it
    twice is safe, and running it again is also how you finish a deletion that
    failed part way.

    What it does **not** do: it does not stop a transmission already in flight, it
    does not cancel a provisioning act that is running, and it is not a guarantee
    that my keyring holds nothing at all for that reference. What is true is the
    weaker thing — no live record names any credential for it any more.

    **Disconnecting everything is not the same as erasing this installation.** If
    what you want is your delete right, that is the offline delete act, not a
    sequence of these.
    """
    code = asyncio.run(_disconnect_account(reference))
    raise typer.Exit(code)


@app.command()
def connections() -> None:
    """Show every account that is connected now, and what state each one is in.

    This is the honest answer to "what have I connected", read from the record: a
    connection whose integration is no longer built, or whose tool is no longer
    registered, is **still listed here**, which is the point — it still exists, its
    credential still exists, and this is where you find the reference in order to
    end it.

    It is also where a **pending** connection shows up. An act that was interrupted
    before it finished leaves a record that is not connectable; nothing is running,
    nothing repairs it, and it would appear nowhere else at all. The remedy is
    always to run the act again, or to disconnect it.

    There is no paging and no ``--limit``: a truncated answer to "what is connected"
    is a false answer rather than a partial one. It is a snapshot taken when you
    asked, not a claim that stays true afterwards.

    It says nothing about permissions — see ``assistant granted`` for those — and
    nothing about *when* anything happened.
    """
    code = asyncio.run(_list_connections())
    raise typer.Exit(code)


@app.command("connection-log")
def connection_log(
    limit: int = typer.Option(
        50,
        "--limit",
        callback=_positive_page_argument,
        help="How many acts to show at most (at least 1).",
    ),
) -> None:
    """Show what was done to connections, in the order it was recorded.

    Every provisioning act and every disconnection is here, one row per act, and
    nothing is ever edited or removed from this list: disconnecting adds a record,
    it does not delete one. That is what makes this the honest answer to "what have
    I connected, and what did I take away".

    **There are no times on it.** A connection record carries no instant, so the
    order is the order I recorded the acts in and nothing more — no row says when,
    and the distance between two rows is not an interval.

    **Do not read liveness off this list.** A row says an act happened, not that it
    still stands, and the page has a bound: a reference whose latest act falls off
    the end would be reported here by an earlier one. ``assistant connections`` is
    what states what is connected now.
    """
    code = asyncio.run(_list_connection_acts(limit=limit))
    raise typer.Exit(code)


@app.command()
def decisions(
    limit: int = typer.Option(
        DEFAULT_PAGE_SIZE,
        "--limit",
        callback=_positive_page_argument,
        help="How many rulings to show at most (at least 1).",
    ),
) -> None:
    """Show what I was allowed to do, what I was refused, and what I asked you about.

    One row per **ruling**, newest ruling first. This is the record the permission
    layer wrote as it decided, and nothing is ever edited or removed from it: a
    question and the answer to it are two rows, not one row that changed.

    **A row says a ruling was made and nothing more.** It does not say the ruling
    still stands, that a grant is current, that an account is still connected, or
    that the tool is still registered under the identifier printed here. It does
    not say the call ever ran, either — this trail bounds what was *decided*, not
    what was done, so nothing here is a receipt.

    **A question with no answer on this page is a fact about the page.** The answer
    may simply be outside it; it is never read as a refusal, an approval, an expiry
    or a wait. Raise ``--limit`` to see further back.

    **Where a ruling was taken over an outbound call** the row also carries the
    connected account, the recipients the ruling was taken over, the description of
    what would have been transmitted, and whether the material this assistant
    selected into the call included a record marked as resting on recorded external
    content — in three states, the third being that the origin was never recorded
    at all, on a row written before that was kept. The payload itself is not in the
    record and is not shown: what binds it is a digest.

    Answering a parked question is ``assistant resume``, never this.
    """
    code = asyncio.run(_list_decisions(limit=limit))
    raise typer.Exit(code)


@app.command("export-decisions")
def export_decisions() -> None:
    """Write the whole permission trail to standard output, as one JSON document.

    Every ruling, not a page of them, and in ``assistant decisions``' order. This is
    the portability half: it is your record of what this assistant was permitted to
    do, in a form another program can read, and it is the whole of it or an error —
    nothing here truncates or samples an export without saying so.

    **The document is a faithful copy.** No key is added, renamed or annotated for
    presentation, so it validates back into exactly the rulings it came from. One
    consequence is worth knowing: on a ruling recorded before this assistant kept
    the call's origin, the origin key is simply **not there**, and that absence is
    the fact. ``assistant decisions`` is where that state is put into words.

    **Only the document goes to standard output** — every message, warning and
    error goes to standard error — so ``assistant export-decisions > trail.json``
    writes an artifact and nothing else. There is no ``--output``: your shell
    already decides where a stream goes, and better than I would.

    This exports **one** store, and is not the whole-installation export.
    """
    code = asyncio.run(_export_decisions())
    raise typer.Exit(code)


@app.command()
def reads(
    limit: int = typer.Option(
        DEFAULT_PAGE_SIZE,
        "--limit",
        callback=_positive_page_argument,
        help="How many read attempts to show at most (at least 1).",
    ),
) -> None:
    """Show the attempts I recorded to read your sources, refusals included.

    One row per **attempt** — the act that starts when I check whether you allow a
    source to be read and ends one of six ways. A refusal is a row like any other,
    and it is the row this record exists for: "was that source read after I
    revoked it?" is answered here by something written down, not by an absence.

    **A row says an attempt was made and how it ended, and nothing further.** It
    does not say the source is still allowed, what you currently allow it for, or
    that the grant it names still exists — ``assistant granted`` is what states
    what you allow now. It does not say what was *done* with anything read,
    either: what a source returned is counted here and nothing more.

    **Nothing the source said is in this record.** There is no content, no entry,
    no path and no location — only which source, what for, when I checked, how it
    ended, the grant it ran under, and how many items came back.

    **The order is the order I recorded them in, newest first.** It is deliberately
    not an ordering by the instant each row shows: two rows can carry instants that
    disagree with their positions, and the position is what the record states.

    **This is what I recorded, which is not quite the same as everything that ever
    happened, and both gaps are worth naming.** The record has a horizon: the
    oldest attempts are dropped as it fills, so ``--limit`` reaches back only as
    far as it still holds. And two faults can leave a read without a row. If I
    cannot write the record I throw the reading away rather than keep it, and
    nothing is written down. If I am shut down while a read is under way, the row
    may be missing — or may already be here — and which of the two it was is not
    something I can tell you afterwards. Nothing came of a read I could not record.

    ``assistant export-reads`` writes what is left, whole.
    """
    code = asyncio.run(_list_reads(limit=limit))
    raise typer.Exit(code)


@app.command("export-reads")
def export_reads() -> None:
    """Write every read attempt I still hold to standard output, as one JSON document.

    **This is the horizon and not the history**, which is the one way it differs
    from ``assistant export-decisions``. That record keeps every ruling ever made
    and drops nothing. This one is capped: when it is full the earliest attempt
    recorded is deleted to make room, so what you get here is every attempt I
    **still hold**, and attempts older than the cap are gone. Nothing in the
    document says otherwise, and nothing here presents the two exports as one
    record of equal completeness.

    Within that horizon it is the whole of it or an error — nothing here truncates
    or samples an export without saying so — and it is in ``assistant reads``'
    order.

    **The document is a faithful copy.** No key is added, renamed or annotated for
    presentation, so it validates back into exactly the records it came from.

    **Only the document goes to standard output** — every message, warning and
    error goes to standard error — so ``assistant export-reads > reads.json``
    writes an artifact and nothing else. There is no ``--output``: your shell
    already decides where a stream goes, and better than I would.

    This exports **one** store, and is not the whole-installation export.
    """
    code = asyncio.run(_export_reads())
    raise typer.Exit(code)


@app.command()
def invocations(
    limit: int = typer.Option(
        DEFAULT_PAGE_SIZE,
        "--limit",
        callback=_positive_page_argument,
        help="How many rows to show at most (at least 1).",
    ),
) -> None:
    """Show what I did on the authorisations you gave me, newest recorded first.

    Where ``assistant decisions`` says what was **decided**, this says what I then
    **did about it**. One attempt writes up to two rows: a *call begun*, recorded
    before I attempt the call, and a *call finished*, recorded after it with how it
    ended and what it cost.

    **A row says I spent an authorisation and attempted a call.** It does not say
    the tool itself was entered — I write the first row before attempting the call,
    and there is a path where the call is abandoned before it starts. One case says
    more: a call that finished *successfully* is the tool answering me back, which
    it could not do without having run.

    **A row with no partner on the page is a fact about the page.** The other half
    may simply be further back, so a *call begun* on its own is never shown as
    pending, in flight, or waiting for anything, and I count nothing from what
    happens to be on screen. Raise ``--limit`` to look further back.

    **What an outbound call did at the other end is not here and is not knowable
    to me.** A row says whether the ruling it **names** was for an outbound call
    and never who or where — that is on the ruling, in ``assistant decisions``. And
    when such a call finishes successfully, what that states is that I attempted it
    and the tool reported success, which is the most the record holds.

    **A cost of "not known" is not a cost of nothing.** Where a tool reports no
    price for an invocation the row says so in those words, because an unknown
    price and a free one are different facts.
    """
    code = asyncio.run(_list_invocations(limit=limit))
    raise typer.Exit(code)


@app.command()
def spend() -> None:
    """Show what the world has cost you today and this month.

    A single noun, taking no argument and no option: ADR-0194 §6 decides the token
    here rather than leaving it to a lane, because a user's script binds to it.

    **Both periods are always shown**, whatever you have configured. Where you have
    set a currency I state what each period has cost; where you have also set a
    ceiling I state that too, and a call whose price would carry the period past it
    is refused before anything runs.

    **What I show is what my own tools reported, not a bill.** It is not an amount
    owed, charged or invoiced by anyone, and I have no way to check it against a
    provider's statement.

    **"Not measurable" is a real answer and not a zero.** A period I cannot measure
    — a call still in flight, or one whose price nobody reported — is stated as
    such rather than summed to a number I would be making up. Where that period has
    a ceiling, nothing further in it will run until the period rolls over or the
    price becomes known.

    **The dates are mine, not yours.** Each period boundary is shown in the zone the
    figures were computed in, labelled with its offset, because that is the zone the
    day and the month were divided by. If your own clock is set elsewhere, that is
    the difference you are seeing rather than an error.
    """
    code = asyncio.run(_show_spend())
    raise typer.Exit(code)


@app.command("export-invocations")
def export_invocations() -> None:
    """Write every act I recorded on an authorisation to standard output, as JSON.

    The portability half for this record, in ``assistant invocations``' order. It
    is the whole of it or an error — nothing here truncates or samples an export
    without saying so. Unlike ``assistant export-reads`` this record is not capped
    and drops nothing, so what you get is the history rather than a horizon.

    **This is a different record from ``assistant export-decisions``**, not a
    superset of it: that one is what was ruled, this one is what was then
    attempted. Neither export is the whole trail on its own, and a program wanting
    both takes both.

    **The document is a faithful copy.** No key is added, renamed or annotated for
    presentation, so it validates back into exactly the rows it came from. One
    consequence is worth knowing: where a call finished without the tool reporting
    a failure kind, the key is simply ``null``, and that absence is the fact.
    ``assistant invocations`` is where that state is put into words.

    **Only the document goes to standard output** — every message, warning and
    error goes to standard error — so ``assistant export-invocations > acts.json``
    writes an artifact and nothing else. There is no ``--output``: your shell
    already decides where a stream goes, and better than I would.

    This exports **one** record, and is not the whole-installation export.
    """
    code = asyncio.run(_export_invocations())
    raise typer.Exit(code)


@device_app.command("enrol")
def device_enrol(
    hub_identity: str = typer.Argument(
        ...,
        metavar="HUB_IDENTITY",
        help="The 'Hub:' value 'ai-assistant-device enrol' printed at the hub.",
    ),
    credential_stdin: bool = typer.Option(
        False,
        "--credential-stdin",
        help="Read the credential from the first line of standard input instead of prompting.",
    ),
) -> None:
    """Store here what the hub printed when it enrolled this device.

    Run ``ai-assistant-device enrol <this device's overlay identity>`` on the hub's
    own machine first: enrolling is a decision only you can make there, and it
    prints two values — the hub's identity and a credential shown **once**.

    Both are stored in this machine's keyring and nowhere else, and they are stored
    **together**: holding one without the other is an incomplete enrolment this
    device refuses to connect on. The credential is never echoed, never logged, and
    never written to any file this program opens.

    If you lose the credential it cannot be recovered — the hub keeps only a
    verifier. Enrol the device again at the hub, which mints a new one in a single
    act and leaves the old verifying against nothing.
    """
    read = _credential_from_stdin if credential_stdin else _prompt_for_credential
    code = asyncio.run(_store_device_enrolment(hub_identity, read))
    raise typer.Exit(code)


@device_app.command("unenrol")
def device_unenrol() -> None:
    """Remove this device's credential and hub identity from this machine.

    It needs no hub and works whether or not the enrolment is still live — which is
    the point of it, because the case you reach for it in is usually one where
    something has already gone wrong. Running it twice is safe.

    **This is the act that purges what a hub-side delete cannot reach.** A delete
    performed at the hub cannot remove a keyring entry on another machine, so it
    reports the devices it could not purge and this is what you run at each of them.

    **It does not revoke anything.** The hub still holds this device's enrolment
    until you revoke it there with ``ai-assistant-device revoke``, and the two are
    independent acts: this one takes the credential off this machine, that one stops
    it admitting anything.
    """
    code = asyncio.run(_remove_device_enrolment())
    raise typer.Exit(code)


async def _store_device_enrolment(hub_identity: str, read_credential: Callable[[], str]) -> int:
    """Load settings, store both values, and say what happened (ADR-0124 §6).

    One error boundary spanning every stage that can fail, as every other command
    here has (ADR-0042 §7): a keyring that is absent or locked, a value this device
    will not hold, a credential these readers refuse, and a configuration that will
    not load are all rendered and mapped to a non-zero exit code rather than escaping
    as a traceback.

    **The credential is read here rather than by the caller** (#1146), which is what
    puts it inside that boundary: both readers refuse by raising ``ValueError`` —
    a stream still going past the widest admissible line, or a hidden prompt asked
    for where standard input is not a terminal — and a refusal raised outside the
    ``try`` would leave as a traceback instead of a rendered line.

    **A refusal, not a failed stream.** An ``OSError`` from the descriptor itself is
    not caught here, and is not caught by :func:`_drive_connect` or
    :func:`_drive_reconnect` either — nothing was read, so it is not a statement
    about the value and the refusals above have nothing to say about it. Deciding
    what all three surfaces render for it is #1940.
    """
    try:
        credential = read_credential()
        settings = load_settings()
        configure_logging(settings)
        await store_enrolment(
            _enrolment_secrets(settings), hub_identity=hub_identity, credential=credential
        )
    except (AssistantError, TransportError, ValueError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    console.print(f"[green]Enrolled.[/] This device is now bound to hub {_safe(hub_identity)}.")
    console.print(
        "Set [bold]ASSISTANT_REMOTE_HUB_ADDRESS[/] to that hub's overlay address to reach it "
        "from here. The address is where to dial; the identity above is what the answer has "
        "to be, and changing one does not change the other."
    )
    return _EXIT_OK


async def _remove_device_enrolment() -> int:
    """Load settings, remove both values, and report what was there (ADR-0124 §8).

    **It reports rather than asserts**, which is the standard ADR-0124 §8 sets for
    the hub-side delete applied on this side of the device boundary: a purge that
    says what it did is a fact the user reads, where one that claims completion is a
    silent shortfall.
    """
    try:
        settings = load_settings()
        configure_logging(settings)
        removed = await remove_enrolment(_enrolment_secrets(settings))
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not removed:
        console.print("This device held no enrolment; nothing changed.")
        return _EXIT_OK
    console.print(
        "[green]Removed[/] the credential and the hub identity from this machine's keyring."
    )
    console.print(
        "The hub still holds this device's enrolment until you revoke it there — run "
        "'ai-assistant-device revoke' on the hub's own machine."
    )
    return _EXIT_OK


async def _open_engine() -> AssistantEngine:
    """Load settings and obtain a client of the running hub (ADR-0084 §6, §9).

    **The one seam the whole of ADR-0084 lands on.** It used to call
    ``build_engine`` and ``Engine.start()``; the process that rendered the prompt
    was the process that opened ``memory.db``. It cannot any more, and not only by
    convention: ADR-0083 ruling 4 makes the hub the only process that opens the
    databases and the API the only door, and the ``interfaces -> app`` import
    contract now makes building an engine here a build failure rather than a
    choice (ADR-0084 §6).

    **The start-up sweeps moved with the engine, which is a gain rather than a
    loss.** ADR-0074 §8 puts the reclaim at engine start, and under a resident hub
    that is once per *process life* instead of once per command a user happens to
    type — and the hub restarts after a crash, so the reclaim that finishes an
    interrupted deletion now runs after every crash rather than at the next command
    (ADR-0083 §3 step 4).

    **A closed door is an instruction, never a fallback** (ADR-0084 §9). The probe
    is what makes that legible *here* rather than at whichever call happens to be
    first: the hub being down is a fact the user reads before anything else is
    rendered. It does not spawn the hub (ruling 3) and does not fall back in-process
    (ruling 5).

    Returns:
        A client of the hub, which is an ``AssistantEngine`` like any other.

    Raises:
        AssistantError: If settings will not load, or the data directory's path
            cannot hold the hub's socket.
        TransportError: If no hub is listening, or the one that answers is not
            this user's, or speaks another protocol version.
    """
    settings = load_settings()
    configure_logging(settings)
    client = _client_for(settings)
    await client.probe()
    return client


def _client_for(settings: Settings) -> HubClient:
    """Build the client this deployment's configuration names (ADR-0124 §1).

    **Which transport is in use is a deployment fact, not a fallback.** ADR-0124 §1
    has a client obtain "its destination from configuration and never from a
    discovery mechanism, a redirect, or anything a peer tells it", and ADR-0084 §9's
    "a closed door is an instruction, never a fallback" applies to the choice as
    well as to the outcome: a remote hub that is down is reported, never quietly
    replaced by the one on this machine.

    **This is where the spoke's process composes its keyring store**, which is the
    one thing here that is more than wiring an argument. ADR-0125 §8 has the
    concrete "reach every consumer by injection from whoever composes it", and on a
    device that is not the hub's this adapter is the only candidate: the import
    contracts forbid ``interfaces -> app`` (ADR-0084 §6) and forbid ``wire`` from
    naming the concrete at all. So it is constructed here, handed straight to the
    client, and used for nothing else — no adapter reads a secret for its own
    purposes, which is golden rule 3 and the harm §8's enumeration is about.

    Args:
        settings: The loaded configuration.

    Returns:
        A client of the hub this device is configured to reach.

    Raises:
        ConfigurationError: If the data directory cannot hold the socket, if the
            configured remote address is not one a conforming hub could bind, or if
            a configured overlay agent socket fails the custody conditions
            (:func:`~ai_assistant.wire.overlay.check_configured_socket`). All three
            are decided here, before anything is opened.
    """
    where = destination(
        data_dir=settings.data_dir,
        remote_address=settings.remote_hub_address,
        remote_port=settings.remote_hub_port,
    )
    match where:
        case LoopbackDestination():
            # The same condition the hub refuses to start on (#554, ADR-0084 §1),
            # checked here so the *client* gives the same diagnosis rather than a
            # bare ``AF_UNIX path too long`` out of ``connect``. One setting locates
            # both the data and the door (§9), so both halves reach the same verdict
            # about it — and the user is told to move the data directory rather than
            # left to infer it.
            check_socket_path(settings.data_dir)
            return HubEngineClient(where.socket_path, read_timeout=settings.hub_read_timeout)
        case RemoteDestination():
            # ADR-0124 §4's second clause: the identity this destination has to
            # match comes from the agent on *this* machine, so where that agent
            # listens is a fact about this device and reaches the seam from the
            # client's own setting (#937). Unset looks at the two packaged paths
            # exactly as before; a configured path is held to the same custody
            # conditions the hub's half runs, phrased in the client's words.
            return RemoteHubEngineClient(
                where,
                read_timeout=settings.hub_read_timeout,
                agent=local_agent(settings.client_overlay_agent_socket),
                secrets=_enrolment_secrets(settings),
            )
        case _:  # pragma: no cover — the union is closed
            assert_never(where)


def _enrolment_secrets(settings: Settings) -> KeyringSecretStore:
    """The device's ``ENROLMENT``-scoped keyring store (ADR-0125 §1, §2).

    Two facts are chosen here and a caller can name neither (ADR-0125 §2): the
    scope, so an object handed out reaches only the entries its job needs, and the
    installation namespace — the resolved ``data_dir``, injected rather than read
    from a setting by the store itself. The second is what stops a second data
    directory on one machine from sharing the first's credentials: the keyring is
    per OS user, not per data directory, so a QA hub's enrolment would otherwise
    overwrite the owner's real one at intake and delete it at unenrolment.

    Args:
        settings: The loaded configuration.

    Returns:
        A store bound to this installation's ``ENROLMENT`` scope. Nothing is opened
        by building it (ADR-0125 §7).
    """
    return KeyringSecretStore(scope=SecretScope.ENROLMENT, installation=str(settings.data_dir))


async def _serve_gateway() -> int:
    """Compose the gateway process and serve until it is stopped (ADR-0168 §1, §9).

    **Nothing is probed.** :func:`_open_engine` probes because a one-shot command
    that cannot reach the hub should say so before rendering anything; a gateway
    must do the opposite — "a gateway that refused to start without a hub would
    present the two failures identically", so it binds regardless and reports the
    hub's absence to whichever browser asks (ADR-0168 §9).

    The client is built by :func:`_client_for`, the same selection the CLI's own
    commands use, because the gateway "obtains the hub only through the promoted
    ``AssistantEngine`` Protocol, by the same client the CLI uses and by the same
    selection between the loopback and remote transports" (ADR-0168 §1).

    Returns:
        The process exit code. Stopping the gateway is an ordinary end rather than
        a failure, so an interrupt exits zero.
    """
    try:
        settings = load_settings()
        configure_logging(settings)
        engine = _client_for(settings)
        await _run_the_gateway(settings, engine)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    except KeyboardInterrupt, asyncio.CancelledError:
        console.print("[dim]Gateway stopped. Every session ended with it.[/]")
    return _EXIT_OK


async def _run_the_gateway(settings: Settings, engine: AssistantEngine) -> None:
    """Serve, and turn a listener that will not bind into a rendered fault (#1436).

    ``Gateway.start`` and ``Gateway.start_remote`` bind with
    ``asyncio.start_server`` and leave a failed bind as a raw ``OSError``, on
    purpose: "the raw errno distinguishes a stay-down fault from a transient one",
    and neither is a statement about a setting the gateway could have checked. That
    is right for the gateway and wrong for the terminal — ADR-0042 §7 puts the
    rendering in this adapter so that a failure "is rendered, not dumped", and a
    port that will not bind is that same rule one layer out. Until this boundary
    existed the bind failure escaped :func:`_serve_gateway` as a hundred-line Rich
    traceback with the one useful sentence at the bottom, on the guide's own
    first-run path (#1436).

    **The errno is carried into the message rather than replaced by it**, for the
    reason it was left raw, and the address comes with it from the operating
    system's own text: this adapter cannot tell which of the two listeners refused,
    since both bind ``gateway_port`` (ADR-0174 §2 gives the remote one no port of
    its own) and only the bind knows which one got there.

    **What it must not do is name a cause it cannot see**, which is why the catch
    is wide and the *claim* is narrow. The bind is not the only thing under this
    ``await`` that raises ``OSError``: ``run_gateway`` reads the front-end bundle
    off the installed distribution (``packaged_bundle``), may stat an overlay
    agent's socket, and the remote listener probes an ephemeral port before it
    binds ``gateway_port`` at all. Adversarial review found on the first round that
    calling all of those "could not bind port 8422" points an operator at the wrong
    subsystem and at a setting that is not the cause. Narrowing the catch would
    take a distinction only ``interfaces/gateway/server.py`` can draw, so
    :func:`_listener_refused` states the port and the remedy for the one errno that
    *is* about the port, and reports the rest as what they are.

    Args:
        settings: The loaded configuration.
        engine: The hub, as the promoted ``AssistantEngine``.

    Raises:
        ConfigurationError: If the gateway could not start. The category is this
            adapter's boundary rather than a claim that a setting is malformed —
            the same conversion :func:`_disclose_bootstrap` already makes of the
            ``OSError`` from a standard output that will not take the value.
    """
    try:
        await run_gateway(
            settings=settings,
            engine=engine,
            disclose=_disclose_bootstrap,
            report=_report_gateway_note,
        )
    except OSError as exc:
        raise _gateway_did_not_start(
            exc,
            port=settings.gateway_port,
            probes_an_address=settings.gateway_remote_address is not None,
        ) from exc


def _gateway_did_not_start(
    exc: OSError, *, port: int, probes_an_address: bool
) -> ConfigurationError:
    """One line for a gateway the operating system would not let start.

    A taken port is the case a stranger following ``docs/guide/first-run.md``
    actually hits — most often a gateway they forgot was running — and
    ``EADDRINUSE`` is the errno that says so. Everything else gets the kernel's own
    refusal and nothing invented on top, because this boundary cannot see which part
    of the start failed (see :func:`_run_the_gateway`): naming the port for an
    unreadable asset bundle or an agent socket would be a confident answer to a
    question that was not asked.

    **``EADDRINUSE`` is not always about ``gateway_port`` either**, which adversarial
    review found on the second round, correctly. ``start_remote`` probes the
    configured overlay address by binding an *ephemeral* port before it binds
    ``gateway_port`` there, and an exhausted ephemeral range raises the same errno —
    on a gateway whose loopback listener has already bound ``gateway_port``
    successfully, since ``serve`` binds that one first. Telling that operator to free
    ``gateway_port`` would name a port that is not the problem.

    Distinguishing the two takes a fact only ``interfaces/gateway/server.py`` holds,
    so this uses the one fact the adapter *does* hold: the probe runs only where a
    remote listener is configured (``gateway_remote_address``). Without one there is
    no ephemeral bind in the path at all and ``EADDRINUSE`` is ``gateway_port``,
    stated flatly — which is every reader of ``first-run.md``. With one, the message
    says an address was in use, names both settings, and leaves the errno's own text
    to say which. It is the round-one repair one level down: claim what is visible
    from here, and no more.

    Args:
        exc: What the start raised.
        port: ``gateway_port``, named only where the errno is about a port.
        probes_an_address: Whether a remote browser listener is configured, and so
            whether an ephemeral bind of its own is in the path.

    Returns:
        The error :func:`_serve_gateway`'s boundary renders and exits non-zero on.
    """
    if exc.errno == errno.EADDRINUSE and not probes_an_address:
        cause = (
            f"could not bind port {port}: {exc}. something else already holds it — most "
            f"often another gateway — so stop that, or set ASSISTANT_GATEWAY_PORT to a "
            f"free port"
        )
    elif exc.errno == errno.EADDRINUSE:
        cause = (
            f"could not bind an address it needed: {exc}. usually that is port {port}, on "
            f"one of the two listeners ASSISTANT_GATEWAY_REMOTE_ADDRESS puts on it — stop "
            f"whatever holds it, or set ASSISTANT_GATEWAY_PORT to a free port. Where the "
            f"errno names no port, it is the overlay address being probed and this machine "
            f"has no ephemeral port left, which is not about either setting"
        )
    else:
        cause = (
            f"could not start: {exc}. that is the operating system's own refusal rather "
            f"than a setting this system checks, so the errno above is what to act on"
        )
    msg = (
        f"the gateway {cause}. It is not serving and admitted no browser, and any "
        f"bootstrap value it printed above is already dead — it ceased with this "
        f"process (ADR-0182 §2)"
    )
    return ConfigurationError(msg)


#: What the owner is told about each of ADR-0182 §1's three reportable conditions.
#: The words live here rather than in the gateway because golden rule 3 keeps the
#: rendering in the adapter, which is ADR-0042 §7's own split one condition over:
#: the gateway decides *which* holds, and this decides how it reads.
_GATEWAY_NOTES: Final[dict[Note, str]] = {
    Note.MINT_ACT_IGNORED: (
        "This gateway could not install the mint act, so it can mint no further "
        "bootstrap value; restart it to get one. SIGUSR1 is set to ignored, so "
        "sending it will not stop the gateway."
    ),
    Note.MINT_ACT_UNSAFE: (
        "This gateway could not install the mint act and could not make SIGUSR1 "
        "safe, so it can mint no further bootstrap value; restart it to get one. "
        "Do not send SIGUSR1 to this process: it would stop the gateway and end "
        "every session with it."
    ),
    Note.MINT_NOT_DISCLOSED: (
        "A bootstrap value could not be written to standard output, so none was "
        "minted. The gateway is still serving, every session is still live, and "
        "any value already outstanding is unchanged."
    ),
}


def _report_gateway_note(note: Note) -> None:
    """Tell the owner one thing about the mint act that carries no value (ADR-0182 §1).

    **Best effort, and deliberately so for one of the three.**
    :data:`Note.MINT_NOT_DISCLOSED` says that standard output refused a write, and
    this system's structured records go to standard output too
    (``PrintLoggerFactory``) — so there is no second channel to fall back to, and a
    report that raised on the way out would turn a mint act the owner can simply
    repeat into a gateway that stopped. The other two are written at start on a
    stream that has not yet failed.

    Args:
        note: The condition the gateway reached.
    """
    with contextlib.suppress(OSError):
        console.print(f"[yellow]{_GATEWAY_NOTES[note]}[/]")


def _disclose_bootstrap(disclosure: Disclosure) -> None:
    """Print the bootstrap value once, on standard output, and nowhere else (ADR-0168 §5).

    **Written straight to the stream rather than through Rich or the logger, and
    both halves of that are deliberate.** §5 forbids the value appearing "in a log
    record, not in an error, not in a response body, and not in any URL a browser
    transmits to a server", and this system's structured records go to standard
    output too — so a logged value would be inside the stream anything parsing
    those records reads. And a console renderer wraps at the terminal's width,
    which would break a value the owner has to paste back whole.

    §5 also requires that "a gateway that cannot disclose its bootstrap value does
    not start, and reports why", which is what the refusal below is: a process
    whose standard output cannot be written to cannot hand the owner the one value
    that admits a browser, so it does not go on to bind a port nobody can use.

    **Three things travel with the value, and none of them is a decision.**
    ADR-0182 §4 puts the live session count and ``gateway_max_sessions`` beside it
    "as **information and not a refusal**, so that an owner minting into a full
    table learns it where they are standing" — the mint act itself "makes no
    decision that depends on the live session count". ADR-0182 §1 puts the act and
    this process's id there so "the act is discoverable from the disclosure rather
    than from a document", and omits both on a gateway that could not make the
    signal safe, because "an advertisement the gateway cannot make safe is an
    instruction to kill it".

    Args:
        disclosure: The value, the origins, the advisory count and the act.

    Raises:
        ConfigurationError: If standard output cannot be written.
    """
    act = disclosure.mint_act
    beside = (
        f"Live sessions: {disclosure.live_sessions} of {disclosure.max_sessions}.\n"
        if act is None
        else (
            f"Live sessions: {disclosure.live_sessions} of {disclosure.max_sessions}. "
            f"For another value: kill -{act.signal} {act.pid}\n"
        )
    )
    try:
        sys.stdout.write(
            f"Assistant gateway listening on {', '.join(disclosure.origins)}\n"
            f"Bootstrap value (good once, and only for this gateway process):\n"
            f"{disclosure.value}\n"
            f"{beside}"
        )
        sys.stdout.flush()
    except OSError as exc:
        msg = (
            "the gateway's bootstrap value could not be written to standard output, "
            "so no browser could be admitted; run it where its output is readable"
        )
        raise ConfigurationError(msg) from exc


async def _ask(
    utterance: str,
    *,
    timeout_seconds: float,
    assume_yes: bool,
    conversation_id: str | None = None,
) -> int:
    """Load settings, build the engine, drive one turn, and close it (ADR-0042 §2, §7).

    One error boundary spans **every** stage that can fail — loading settings,
    configuring logging, constructing the engine, driving the turn, and shutting
    down — so any :class:`AssistantError` is rendered and mapped to a non-zero exit
    code rather than escaping as a traceback (§7). Returns the process exit code.
    The composition root owns constructing the façade; this adapter owns closing it.

    ``conversation_id`` arrives non-blank and already stripped, which is the whole of
    what :func:`_present_optional_id` does to it (ADR-0085 §3c). Whether it *names* a
    conversation is the engine's question, and an unknown one comes back as an
    ``AssistantError`` this boundary renders rather than as a silently fresh
    conversation (ADR-0074 §1).
    """
    timeout = timedelta(seconds=timeout_seconds)  # already validated positive + finite
    approver: Callable[[Confirmation], bool] = (
        (lambda _confirmation: True) if assume_yes else _prompt_for_approval
    )
    # A routed card is rendered by `_render_turn` before this is reached (ADR-0197 §7,
    # ADR-0073 §5), so `--yes` supplies the answer and never the rendering here either:
    # a non-interactive approval must not destroy what the user never saw.
    confirm_operation: Callable[[OperationConfirmation], bool] = (
        (lambda _card: True) if assume_yes else _confirm_operation
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_turn(
        engine,
        utterance,
        timeout=timeout,
        approver=approver,
        confirm_operation=confirm_operation,
        conversation_id=conversation_id,
    )


async def _list_conversations(*, limit: int, offset: int) -> int:
    """Load settings, build the engine, list conversations, and close it (ADR-0074 §2).

    The continuity counterpart to :func:`_ask`, with the same single error boundary
    (ADR-0042 §7). The paging arguments were already checked against the store's
    accepted range at parse time (:func:`_page_argument`), so the one failure that
    is not an ``AssistantError`` cannot reach here.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_conversations(engine, limit=limit, offset=offset)


async def _forget_conversation(conversation_id: str, *, assume_yes: bool) -> int:
    """Load settings, build the engine, run the deletion ceremony, and close it.

    The conversation-scoped counterpart to :func:`_forget_belief`, with the same
    single error boundary (ADR-0042 §7) and the same rule about ``--yes``: it
    supplies the answer and never the rendering, because a non-interactive approval
    must not destroy what the user never saw (ADR-0073 §5, ADR-0052 §4).
    """
    confirm: Callable[[ConversationDigest], bool] = (
        (lambda _digest: True) if assume_yes else _confirm_forget_conversation
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget_conversation(engine, conversation_id, confirm=confirm)


async def _search_transcript(query: str, *, limit: int, offset: int) -> int:
    """Load settings, build the engine, search the archive, and close it (ADR-0225 §7)."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_transcript_search(engine, query, limit=limit, offset=offset)


async def _read_transcript_conversation(conversation_id: str, *, limit: int, offset: int) -> int:
    """Load settings, build the engine, read one conversation's transcript, and close it."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_transcript_conversation(engine, conversation_id, limit=limit, offset=offset)


async def _read_transcript_entry(address: str) -> int:
    """Load settings, build the engine, read one entry whole, and close it."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_transcript_entry(engine, address)


async def _export_transcript(*, limit: int, offset: int) -> int:
    """Load settings, build the engine, enumerate the archive, and close it (ADR-0225 §7)."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_transcript_export(engine, limit=limit, offset=offset)


async def _forget_transcript_entry(address: str, *, assume_yes: bool) -> int:
    """Load settings, build the engine, run the entry deletion ceremony, and close it.

    ``--yes`` supplies the answer and never the rendering, on
    :func:`_forget_conversation`'s rule: a non-interactive approval must not destroy
    what the user never saw (ADR-0073 §5).
    """
    confirm: Callable[[TranscriptEntry | None], bool] = (
        (lambda _entry: True) if assume_yes else _confirm_forget_transcript
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget_transcript_entry(engine, address, confirm=confirm)


async def _forget_transcript_conversation(conversation_id: str, *, assume_yes: bool) -> int:
    """Load settings, build the engine, run the transcript deletion ceremony, and close it."""
    confirm: Callable[[tuple[TranscriptEntry, ...]], bool] = (
        (lambda _page: True) if assume_yes else _confirm_forget_transcript_conversation
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget_transcript_conversation(engine, conversation_id, confirm=confirm)


async def _resume_pending(*, timeout_seconds: float, assume_yes: bool) -> int:
    """Recover durably-parked confirmations, answer them, and close the engine (ADR-0052).

    The restart-recovery counterpart to :func:`_ask`: it builds the engine over the
    same durable stores an earlier run wrote, asks the façade for the confirmations
    still awaiting an answer, and resolves each. One error boundary spans every
    stage that can fail — loading settings, building the engine, recovering,
    resuming, and shutdown — so an :class:`AssistantError` is rendered and mapped to
    a non-zero exit code rather than escaping (ADR-0042 §7).
    """
    timeout = timedelta(seconds=timeout_seconds)  # already validated positive + finite
    # _drive_resume renders each recovered action itself (below), so the approver
    # only decides yes/no — a bare confirm, not _prompt_for_approval, or the action
    # would be rendered twice interactively.
    approver: Callable[[Confirmation], bool] = (
        (lambda _confirmation: True) if assume_yes else _confirm
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_resume(engine, timeout=timeout, approver=approver)


async def _learn_feedback(  # noqa: PLR0913 — one parameter per field of the event this builds, each a separate thing the user said
    content: str,
    *,
    kind: FeedbackKind,
    memory_kind: MemoryKind | None,
    subject: str | None,
    about_person: str | None,
    guarded: bool,
) -> int:
    """Load settings, build the engine, submit the feedback, and close it (ADR-0042 §2, §7).

    The correction-leg counterpart to :func:`_ask`. It builds the
    :class:`~ai_assistant.core.types.FeedbackEvent` from the parsed flags — parsing
    input into the engine's request type is the adapter's own job (ADR-0042 §6) —
    then one error boundary spans every stage that can fail: loading settings,
    configuring logging, constructing the engine, the learn call, and shutdown, so
    an :class:`AssistantError` is rendered and mapped to a non-zero exit code rather
    than escaping (§7). The composition root builds the façade; this adapter closes
    it. Returns the process exit code.

    ``memory_kind`` is relayed exactly as the caller resolved it, ``None`` included:
    an absent value is a *state of the request*, not a value to fill in here
    (ADR-0122 §2), and the field's own default would fill it in the same way.

    ``guarded`` is relayed the same way and is **set explicitly even when it is
    ``False``**, rather than left to the field's default. The two values are the
    same value, and stating it is what keeps this constructor honest about the flag
    it was handed: an adapter that accepted ``--guarded`` and then omitted the
    member here would write the default placement over an explicit owner act, which
    is the one failure the route exists to prevent (ADR-0217 §10). Nothing is
    interpreted on the way — the flag is a field this sets and `learning` reads
    (ADR-0217 §7, ``CLAUDE.md``'s third golden rule).
    """
    event = FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        about_person=about_person,
        created_at=_utcnow(),
        guarded=guarded,
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_learn(engine, event)


async def _list_beliefs(
    *,
    bands: list[BeliefBand] | None,
    kinds: list[MemoryKind] | None,
    limit: int,
    offset: int,
) -> int:
    """Load settings, build the engine, list the beliefs, and close it (ADR-0073 §7).

    The inspection counterpart to :func:`_ask`. One error boundary spans every stage
    that can fail — loading settings, configuring logging, constructing the engine,
    the read, and shutdown — so an :class:`AssistantError` is rendered and mapped to
    a non-zero exit code rather than escaping (ADR-0042 §7). The paging arguments
    were already checked against the store's accepted range at parse time
    (:func:`_page_argument`), so the one failure that is not an ``AssistantError``
    cannot reach here.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_beliefs(engine, bands=bands, kinds=kinds, limit=limit, offset=offset)


async def _list_questions(*, limit: int, offset: int) -> int:
    """Load settings, build the engine, list the questions, and close it (ADR-0078 §8).

    The deferred-question counterpart to :func:`_list_beliefs`, with the same single
    error boundary (ADR-0042 §7). The paging arguments were already checked against
    the store's accepted range at parse time (:func:`_page_argument`), so the one
    failure that is not an ``AssistantError`` cannot reach here.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_questions(engine, limit=limit, offset=offset)


async def _answer_question(question_id: str, *, accept: bool) -> int:
    """Load settings, build the engine, answer one question, and close it (§9).

    The same single error boundary every other command has (ADR-0042 §7). The id
    arrives non-blank and already stripped (:func:`_present_id`, ADR-0085 §3c);
    whether it *names* an open question is the engine's question, and one that does
    not comes back as an ordinary outcome rather than an error.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_answer(engine, question_id, accept=accept)


async def _forget_question(question_id: str) -> int:
    """Load settings, build the engine, destroy one question, and close it (§9 step 1).

    **No show-then-confirm ceremony, and that is a deliberate difference from
    ``forget``/``forget-conversation``.** Those destroy *beliefs* — what the assistant
    holds about the user — so ADR-0073 §5 requires the thing be rendered before
    consent is taken. A question is emphatically **not** a belief of any band
    (ADR-0078 §1): nothing is being un-believed, the correction it holds is one the
    user can simply re-`learn`, and ADR-0073 §6 names ``DeferralStore.delete`` as
    exactly the verb for "destroy the record of having been asked". Showing it first
    would also need a single-question read the façade does not have and ADR-0078 §8
    does not name, and ``assistant questions`` has already rendered the question
    together with the two recovery steps this call is step 1 of.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget_question(engine, question_id)


async def _observe_conversation(conversation_id: str | None) -> int:
    """Load settings, build the engine, run one observation pass, and close it.

    The accumulation counterpart to :func:`_learn_feedback`, with the same single
    error boundary (ADR-0042 §7): every stage that can fail — loading settings,
    configuring logging, constructing the engine, the observation itself, and
    shutdown — is inside it, so an :class:`AssistantError` is rendered and mapped to
    a non-zero exit code rather than escaping as a traceback. The id arrives
    non-blank and already stripped, exactly as ``ask --conversation``'s does
    (:func:`_present_optional_id`, ADR-0085 §3c): whether it *names* a conversation
    is the engine's question (ADR-0074 §1).
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_observe(engine, conversation_id)


async def _list_sources() -> int:
    """Obtain a client, enumerate the grantable sources, and render them.

    The grant-surface counterpart to :func:`_list_beliefs`, with the same single
    error boundary (ADR-0042 §7).
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_sources(engine)


async def _grant_source(source: str, *, scope: list[GrantScope], assume_yes: bool) -> int:
    """Obtain a client, show the source, take the answer, and grant (ADR-0102 §6).

    ``--yes`` supplies the answer and never the rendering, for
    :func:`_forget_belief`'s reason turned around: there a person cannot consent to
    destroying something they were not shown, and here a person cannot consent to a
    source they were not shown. ADR-0097 §9a is the clause, and ADR-0102 §6's third
    normative clause is what binds *this* module: a client renders ``location`` and
    takes an explicit act before it sends ``grant``.
    """
    confirm: Callable[[GrantableSource], bool] = (
        (lambda _source: True) if assume_yes else _confirm_grant
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_grant(engine, source, scope=scope, confirm=confirm)


async def _revoke_source(source: str) -> int:
    """Obtain a client, withdraw the grant, and say what happened.

    **No ceremony, and that is a decision rather than an omission** (ADR-0102 §4).
    ``forget`` and ``forget-conversation`` show-then-confirm because they *destroy*
    what the assistant holds (ADR-0073 §5); revoking destroys nothing — it is
    prospective, retires no belief and deletes no record (ADR-0097 §6). What it is,
    is the user's whole remedy, and ADR-0102 §4 is explicit that nothing may stand
    between them and it: a prompt here would be one more thing to get past at the
    moment someone has decided to withdraw consent.

    It is also why this sends ``revoke`` **without** consulting
    ``grantable_sources`` first. That lookup would reintroduce, client-side, exactly
    the admission check §4 removed from the operation — and it would fail for the
    one case the removal exists for: a grant whose reader has since been
    unconfigured, which is unrevokable the moment anything checks.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_revoke(engine, source)


async def _list_grants(*, limit: int) -> int:
    """Obtain a client, read the grant record, and render it (ADR-0097 §4)."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_grants(engine, limit=limit)


async def _list_standing() -> int:
    """Obtain a client, read what is currently authorised, and render it (ADR-0139 §2)."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_standing(engine)


async def _amend_source(source: str, *, scope: list[GrantScope], assume_yes: bool) -> int:
    """Obtain a client and run the two-act amendment (ADR-0139 §4, §5).

    ``--yes`` supplies the answer and never the rendering, exactly as on
    :func:`_grant_source`: ADR-0139 §5 applies ADR-0102 §6's disclosure to **every**
    ``grant``, the granting half of an amendment included, and refuses every reason
    a client might have for skipping it — that the new scope is narrower, that the
    source was granted a moment ago, or that the user has granted it before.
    """
    confirm: Callable[[GrantableSource], bool] = (
        (lambda _source: True) if assume_yes else _confirm_amendment
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_amend(engine, source, scope=scope, confirm=confirm)


async def _list_notifications(*, limit: int, offset: int) -> int:
    """Obtain a client, read the held notifications, and render them (ADR-0130 §7).

    The notification counterpart to :func:`_list_questions`, with the same single
    error boundary (ADR-0042 §7). The paging arguments were already checked against
    the range the engine refuses outside of at parse time (:func:`_page_argument`),
    so the one failure that is not an ``AssistantError`` cannot reach here.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_notifications(engine, limit=limit, offset=offset)


async def _dismiss_notification(notification_id: str) -> int:
    """Obtain a client, dismiss one notification, and say what happened (ADR-0130 §9).

    **No show-then-confirm ceremony**, for :func:`_forget_question`'s reason and one
    more of its own. A held notification is not a belief of any band, so ADR-0073 §5's
    requirement to render before destroying does not reach it — and a dismissal
    destroys nothing at all: the record stays readable and stays in the export
    (ADR-0130 §9). What ends is its actionability, which is what ``assistant
    notifications`` has already shown the user before they typed this.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_dismiss_notification(engine, notification_id)


async def _forget_notification(notification_id: str) -> int:
    """Obtain a client, destroy one notification, and say what happened (ADR-0130 §9).

    **No ceremony either, and that is ADR-0130 §9's own instruction rather than this
    module's convenience**: the per-record delete lands "in the shape
    ``forget_question`` takes", and :func:`_forget_question` is where the reasoning
    for that shape is written down — a question is not a belief, so nothing is being
    un-believed and ADR-0073 §5 does not reach it. Neither is a notification: it is a
    proposal about a moment, the user has just read it in ``assistant
    notifications``, and showing it again would need a single-record read the façade
    does not have and ADR-0130 §9 does not name.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget_notification(engine, notification_id)


async def _show_notification_settings() -> int:
    """Obtain a client, read the three standing settings, and render them (§6)."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_notification_settings(engine)


async def _tune_notifications(asked: _Tuning) -> int:
    """Obtain a client and write the standing settings the user named (ADR-0130 §6).

    The tuning counterpart to :func:`_grant_source`, with the same single error
    boundary (ADR-0042 §7). The flags were already checked against each other and
    parsed at parse time (:func:`_tuning`), so the failures that are not an
    ``AssistantError`` cannot reach here.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_tune(engine, asked)


def _prompt_for_credential() -> str:
    """Read the credential from the terminal without echoing it (I/O; ADR-0042 §6).

    The one hidden prompt on this surface — ``connect``, ``reconnect`` and ``device
    enrol`` all reach it (#1146) — and hidden for the reason each of them shares: a
    Tier 0 value must not be left on screen, in a scrollback buffer, or in whatever
    records a terminal session.

    **It refuses a standard input that is not a terminal**, and that is a refusal
    about what the hidden prompt degenerates into rather than a policy about pipes.
    ``getpass`` reaches for the controlling terminal first; where there is none — a
    container, a CI job, a daemon — it falls back to
    :func:`~getpass.fallback_getpass`, which prints "Password input may be echoed"
    and then reads ``sys.stdin.readline()`` **unbounded**. Both halves of that are
    wrong for a Tier 0 value: the echo is the disclosure ``hide_input`` was asked
    for, and the unbounded read materialises a stream with no newline in it before
    :func:`_credential` can apply any bound. ``--credential-stdin`` is the door for
    a value arriving on a pipe and is bounded by construction, so the remedy is
    named rather than silently substituted.

    The test is on ``sys.stdin`` rather than on whether ``/dev/tty`` opens, which is
    what ``getpass`` actually branches on. It is the more conservative of the two:
    it also refuses the case where stdin is redirected *and* a terminal exists,
    where ``getpass`` would have prompted the human and been perfectly safe. That
    case is a person who redirected standard input and then expected to be asked
    anyway, and it costs them one flag.

    Returns:
        The line the user typed, without its terminator and otherwise unaltered.

    Raises:
        ValueError: If standard input is not a terminal. The message names the flag
            to use instead, and nothing about any value.
    """
    if not sys.stdin.isatty():
        msg = (
            "a credential is prompted for at a terminal, and standard input here is "
            "not one; pipe it in with --credential-stdin instead, which is bounded "
            "and never echoed"
        )
        raise ValueError(msg)
    # Annotated rather than returned directly: ``typer.prompt`` is typed ``Any``, and
    # a bare return would silently widen this function's declared contract to it.
    typed: str = typer.prompt("Credential", hide_input=True)
    return typed


#: The most this surface reads from standard input for one credential.
#:
#: :data:`~ai_assistant.core.types.SECRET_VALUE_MAX_BYTES` plus a two-byte
#: terminator, which is the widest input that can still be *inside* the bound: a
#: maximal credential followed by ``\r\n``. A stream still going at that point
#: cannot be an admissible secret whatever follows, so the refusal is decidable
#: from what has been read — and reading no further is what keeps a pipe with no
#: newline in it a refusal rather than an allocation.
_CREDENTIAL_READ_LIMIT: Final[int] = SECRET_VALUE_MAX_BYTES + 2


def _credential_from_stdin() -> str:
    r"""Read the credential from the first line of standard input (I/O; ADR-0042 §6).

    **The line terminator is removed and nothing else is**, and that holds for every
    credential this surface reads — ``connect``, ``reconnect`` and ``device enrol``
    alike (#1146). An integration credential is whatever the service issued, and
    ADR-0125 §3 is explicit that "two spellings of a secret are two different
    secrets" and that helpfully removing a trailing character "would produce an
    authentication failure nobody could reproduce by inspection". A hub-minted
    enrolment credential comes from an alphabet with no whitespace in it (ADR-0124
    §6), so a ``strip()`` there could not change a *conforming* value — but that is
    an invariant held by the minting alphabet rather than by this reader, spent at
    the one moment a user cannot re-read the value, and a padded line is better
    refused than silently repaired. A leading space
    in a pasted token is admissible and is kept — and so is a **trailing carriage
    return**, which is why the terminator is matched as a unit rather than stripped
    one character at a time. ``sys.stdin`` hands a final ``\r`` through untranslated
    (there is no following byte to make it a newline), so a chained
    ``removesuffix("\n").removesuffix("\r")`` would silently shorten a credential
    that legitimately ends in one.

    **It is read as bytes, and bounded.** Text-mode ``readline`` would decode
    before this function could measure anything, and an unterminated stream would
    be materialised whole before :func:`_credential` applied the 1024-byte bound —
    so a pipe with no newline in it is an allocation rather than a refusal. Reading
    one byte past the widest admissible line makes the refusal decidable here.

    Decoding is ``surrogateescape`` rather than strict **because a
    ``UnicodeDecodeError`` is a ``ValueError`` carrying the offending bytes**, and
    this surface renders the ``ValueError`` it catches. A byte sequence that is not
    UTF-8 therefore comes back as unencodable text and is refused by
    :func:`~ai_assistant.core.types.secret_value`, whose message ADR-0125 §6
    guarantees carries no part of the value.

    Returns:
        The first line, less exactly one ``\r\n`` or ``\n``.

    Raises:
        ValueError: If the stream is still going past the widest line an
            admissible credential can occupy. The message names the bound, which
            ADR-0125 §6 permits, and neither the value nor its length, which it
            does not.
    """
    chunk = sys.stdin.buffer.readline(_CREDENTIAL_READ_LIMIT)
    if len(chunk) >= _CREDENTIAL_READ_LIMIT and not chunk.endswith(b"\n"):
        msg = (
            f"a secret value must encode to at most {SECRET_VALUE_MAX_BYTES} UTF-8 "
            "bytes, and this line was still going past that"
        )
        raise ValueError(msg)
    if chunk.endswith(b"\r\n"):
        line = chunk[:-2]
    elif chunk.endswith(b"\n"):
        line = chunk[:-1]
    else:
        line = chunk
    return line.decode("utf-8", errors="surrogateescape")


def _credential(plaintext: str) -> SecretStr:
    """Wrap and validate one supplied credential, before anything is opened.

    ADR-0125 §3 makes :func:`~ai_assistant.core.types.secret_value` the only
    supported way to build one: :data:`~ai_assistant.core.types.SecretValue` is an
    ``Annotated`` alias, so constructing the origin directly satisfies every static
    check while the validator never runs. Revalidating here is the seam's own rule
    applied at the door, and it makes the refusal local — a blank or oversized
    credential is refused before a frame is built rather than after.

    Args:
        plaintext: What the user typed or piped, unaltered.

    Returns:
        The value in its redacting holder.

    Raises:
        ValueError: If the plaintext is blank, has no UTF-8 encoding, or exceeds
            the contract bound. The message names neither the value nor its length
            (ADR-0125 §6), which is what makes it safe to print.
    """
    return secret_value(SecretStr(plaintext))


async def _connect_account(identity: str, *, credential_stdin: bool) -> int:
    """Obtain a client, show the identity, take the credential, and connect.

    **The hub is reached before the credential is asked for**, which is the one
    ordering decision in this function. A client that prompted first would ask a
    person for a secret in order to discover that nothing is listening — and the
    natural response to that is to run it again and type it a second time.

    The single error boundary is :func:`_list_sources`' (ADR-0042 §7).
    """
    read = _credential_from_stdin if credential_stdin else _prompt_for_credential
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_connect(engine, identity, read_credential=read)


async def _reprovision_account(reference: str, *, identity: str, credential_stdin: bool) -> int:
    """Obtain a client, show the identity, take the credential, and re-provision."""
    read = _credential_from_stdin if credential_stdin else _prompt_for_credential
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_reconnect(engine, reference, identity=identity, read_credential=read)


async def _disconnect_account(reference: str) -> int:
    """Obtain a client, disconnect the reference, and say exactly what went.

    **No ceremony, and that is a decision rather than an omission**, on ADR-0102
    §4's reasoning transposed to ADR-0149 §5's act. ``forget`` shows-then-confirms
    because it destroys something the user would have to have been shown to consent
    to destroying; a disconnection destroys a credential whose whole point is that
    the user has decided it should stop working, and ADR-0151 §8 makes the act
    idempotent and re-runnable so a mistaken one costs nothing to correct.

    It also sends ``disconnect_account`` **without** reading ``connected_accounts``
    first. That read would be a liveness claim the client then acted on, which is
    the inference ADR-0151 §7 and §9 keep apart everywhere else on this surface —
    and it would fail for the one case a disconnection exists for, a reference whose
    record the client could not read. What the user is told comes from the act's own
    answer, which carries the record it removed.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_disconnect(engine, reference)


async def _list_connections() -> int:
    """Obtain a client, read what is connected now, and render it (ADR-0151 §9)."""
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_connections(engine)


async def _list_connection_acts(*, limit: int) -> int:
    """Obtain a client, read what was done to connections, and render it (ADR-0151 §12).

    This is the operation that discharges the record half of ADR-0004 §7 for a
    provisioning act: the connection store is append-only, and a store the owner
    cannot read is not a discharge of "transparent and reviewable".
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_connection_acts(engine, limit=limit)


async def _list_decisions(*, limit: int) -> int:
    """Obtain a client, read the bounded listing, and render it (ADR-0186 §9).

    :func:`_list_connection_acts`' shape over the other append-only record. The
    error boundary is this surface's usual one and writes to :data:`console`,
    because a listing is prose on a terminal — it is ``export-decisions`` alone
    whose standard output is an artifact.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_decisions(engine, limit=limit)


async def _export_decisions() -> int:
    """Obtain a client, read the whole trail, and write the artifact (ADR-0186 §9).

    **Standard output is claimed for the document before anything else runs**, and
    the stream this command was handed is kept so the artifact can still reach it.
    Everything the command does in between — the settings load, the logging
    configuration, the probe, the call — prints to standard error instead, whatever
    it prints and whether or not this module wrote it. §9's clause is about the
    *stream* rather than about this function's own politeness: "one JSON document
    written to standard output … and nothing else on that stream", and a redirect
    is the only way to say that about code this adapter does not own.

    It is not defensive about a hazard that does not exist yet, either: `structlog`
    is configured with a ``PrintLoggerFactory``, whose default file is
    ``sys.stdout``, so the first log line emitted anywhere on the client path would
    land in the middle of a user's export. Nothing on that path logs today, which is
    exactly the state that changes without anyone thinking about this command.
    """
    artifact = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        try:
            engine = await _open_engine()
        except (AssistantError, TransportError) as exc:
            _render_error(exc, to_stderr=True)
            return _EXIT_ERROR

        return await _drive_export_decisions(engine, artifact=artifact)


async def _list_reads(*, limit: int) -> int:
    """Obtain a client, read the bounded listing, and render it (ADR-0186 §10).

    :func:`_list_decisions`' shape over the read trail, and deliberately the same
    shape: §10 mints "a **second pair** mirroring §1's", so a door that differed
    here would be a difference the contract does not have.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_reads(engine, limit=limit)


async def _export_reads() -> int:
    """Obtain a client, read the whole trail, and write the artifact (ADR-0186 §10).

    :func:`_export_decisions`' claim on standard output, for the same reason and by
    the same means: the stream is claimed for the document before anything else
    runs, and everything in between — the settings load, the logging configuration,
    the probe, the call — prints to standard error instead, whatever prints it and
    whether or not this module wrote it. §9's clause is about the *stream*, and a
    redirect is the only way to say that about code this adapter does not own.
    """
    artifact = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        try:
            engine = await _open_engine()
        except (AssistantError, TransportError) as exc:
            _render_error(exc, to_stderr=True)
            return _EXIT_ERROR

        return await _drive_export_reads(engine, artifact=artifact)


async def _list_invocations(*, limit: int) -> int:
    """Obtain a client, read the bounded listing, and render it (ADR-0192 §4).

    :func:`_list_decisions`' shape over the same store's third pair, and
    deliberately the same shape: the operations are two more reads on one trail, so
    a door that differed here would be a difference the contract does not have.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_invocations(engine, limit=limit)


async def _show_spend() -> int:
    """Obtain a client, read the two totals, and render them (ADR-0194 §6).

    :func:`_list_invocations`' shape over a different read on the same store, and
    deliberately the same shape: a door that differed here would be a difference
    the contract does not have.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_spend(engine)


async def _export_invocations() -> int:
    """Obtain a client, read every invocation row, and write the artifact (ADR-0192 §4).

    :func:`_export_decisions`' claim on standard output, for the same reason and by
    the same means: the stream is claimed for the document before anything else
    runs, and everything in between — the settings load, the logging configuration,
    the probe, the call — prints to standard error instead, whatever prints it and
    whether or not this module wrote it. ADR-0186 §9's clause is about the
    *stream*, and a redirect is the only way to say that about code this adapter
    does not own.
    """
    artifact = sys.stdout
    with contextlib.redirect_stdout(sys.stderr):
        try:
            engine = await _open_engine()
        except (AssistantError, TransportError) as exc:
            _render_error(exc, to_stderr=True)
            return _EXIT_ERROR

        return await _drive_export_invocations(engine, artifact=artifact)


async def _forget_belief(belief_id: str, *, assume_yes: bool) -> int:
    """Load settings, build the engine, run the deletion ceremony, and close it.

    The deletion counterpart to :func:`_ask`, with the same single error boundary
    (ADR-0042 §7). ``--yes`` supplies the answer but not the rendering: the belief is
    displayed either way, because a person cannot consent to destroying something
    they were not shown and a non-interactive approval must not destroy what the user
    never saw (ADR-0073 §5, ADR-0052 §4).
    """
    confirm: Callable[[Belief], bool] = (lambda _belief: True) if assume_yes else _confirm_forget
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget(engine, belief_id, confirm=confirm)


async def _drive_beliefs(
    engine: AssistantEngine,
    *,
    bands: list[BeliefBand] | None,
    kinds: list[MemoryKind] | None,
    limit: int,
    offset: int,
) -> int:
    """Ask the façade for one page of beliefs and render it (ADR-0073 §7).

    The adapter relays the filters and renders what comes back. It re-filters
    nothing, re-orders nothing, reads no clock, and computes no band — the page's
    membership and order are the store's contract and each row's band was projected
    in the engine (ADR-0072 §7, ADR-0073 §7).
    """
    try:
        page = await engine.beliefs(bands=bands, kinds=kinds, limit=limit, offset=offset)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_beliefs(page, limit=limit, offset=offset)
    return _EXIT_OK


async def _drive_forget(
    engine: AssistantEngine, belief_id: str, *, confirm: Callable[[Belief], bool]
) -> int:
    """Show the belief, take the answer, and destroy it if the answer is yes.

    Show-then-confirm, in that order (ADR-0073 §5): the render is taken as late as
    it can be — immediately before the question — so the window in which a write can
    land between what was shown and what is destroyed is the human's answering time
    and nothing longer. That window is named rather than closed, and the consent
    collected is consent to forget *the belief that id names*, which is what
    :func:`_render_forget_prompt` says.

    A refusal is a valid outcome and exits 0. An id naming no live belief, and a
    delete that finds nothing left to destroy, are both reported and exit non-zero
    (ADR-0073 §7).
    """
    try:
        belief = await engine.belief(belief_id)
        if belief is None:
            _render_no_such_belief(belief_id)
            return _EXIT_ERROR
        _render_forget_prompt(belief)
        if not confirm(belief):
            console.print("[dim]Left alone. Nothing was forgotten.[/]")
            return _EXIT_OK
        destroyed = await engine.forget(belief.id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print("[yellow]Nothing to forget:[/] that belief was already gone.")
        return _EXIT_ERROR
    console.print("[green]Forgotten.[/] That belief is destroyed — it is in no export.")
    return _EXIT_OK


async def _drive_resume(
    engine: AssistantEngine,
    *,
    timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, relayed to the façade (ADR-0029 §4)
    approver: Callable[[Confirmation], bool],
) -> int:
    """Recover the pending confirmations and resolve each one.

    Renders each recovered action so a person can judge it, collects the yes/no,
    and relays the opaque token via ``resume`` — the adapter transports consent, it
    authors no ruling (ADR-0042 §6). Rendering happens here, **before** the
    approver, so the action and the policy's reason are shown whether the answer is
    interactive or supplied by ``--yes`` (ADR-0052 §4): a non-interactive approval
    must not run a recovered action the user never saw. An :class:`AssistantError`
    from any stage is rendered and mapped to a non-zero exit code.
    """
    failed = False
    try:
        pending = await engine.pending_confirmations()
        if not pending:
            console.print("[dim]Nothing is awaiting confirmation.[/]")
            return _EXIT_OK
        for confirmation in pending:
            _render_confirmation(confirmation)
            approved = approver(confirmation)
            resumed = await engine.resume(confirmation.token, approved=approved, timeout=timeout)
            failed = _render_turn(resumed) or failed
            _render_conversation_footer(resumed)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    return _EXIT_ERROR if failed else _EXIT_OK


async def _drive_turn(  # noqa: PLR0913 — one parameter per seam a turn is driven through, and the two approvers are two card types
    engine: AssistantEngine,
    utterance: str,
    *,
    timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, relayed to the façade (ADR-0029 §4)
    approver: Callable[[Confirmation], bool],
    confirm_operation: Callable[[OperationConfirmation], bool],
    conversation_id: str | None = None,
) -> int:
    """Stream a turn, render it, and relay a confirmation if the engine parks one.

    **The turn is driven through** :meth:`AssistantEngine.converse_streaming`
    (ADR-0173 §4), so the answer reaches the screen while it is still being
    composed. That method is subject to every clause ``converse`` declares — same
    arguments, same refusals, same failures, the same ``timeout`` budget relayed
    unchanged — and the terminal :class:`TurnOutcome` it yields last is the one this
    function goes on to render. The only outcome shape that reaches here and could
    not reach ``converse`` is ADR-0173 §6's fourth: a :attr:`~TurnOutcome.reply` set
    beside ``reply_degraded``, which :func:`_render_reply` renders per ADR-0173 §10.

    **Iteration stops at the terminal frame and the iterator is closed either way.**
    ADR-0173 §4 makes closing the caller's obligation and it is what hangs up the
    connection, so the loop runs inside :func:`closing_stream`: breaking on the
    outcome, an :class:`AssistantError` from the iteration, and a
    ``KeyboardInterrupt`` or cancellation at any point all release the connection
    rather than leaving a generator nobody finished. A stream abandoned mid-answer
    does not abandon the *turn* (§9) — the hub runs it to completion and captures it
    — but the socket is the adapter's to give back.

    **And so is the line the answer was written on.** It is written with no ending so
    the next chunk can continue it (§10), which means every exit from the read owes
    :meth:`_StreamedReply.abandon` — including the two that are not errors and are
    re-raised untouched, since ``asyncio.CancelledError`` and ``KeyboardInterrupt``
    are ``BaseException`` and pass the handler that catches an
    :class:`AssistantError`. That is the whole of what the last handler below does:
    the exception's own path is unchanged, and what would otherwise be left is the
    owner's next shell prompt on the same line as half a sentence (#1352).

    **A routed park is answered through the same method and is not the same park**
    (ADR-0197 §7). It carries an ``OperationConfirmation`` rather than a
    ``Confirmation``, its refusal comes back as ``RouteOutcome.REFUSED`` on the
    outcome rather than as a raised ``PermissionDeniedError``, and it is never both:
    §8 makes ``routed`` and ``step`` mutually exclusive, so exactly one of the two
    branches below can be taken. It is also **not recoverable** — §7 keeps a routed
    park out of ``pending_confirmations`` and out of a restart — so ``assistant
    resume`` never meets one and this is the only place a routed card is answered.

    A turn drives at most one step today (ADR-0042 §3), so at most one
    confirmation can arise; ``resume`` resolves it to ``EXECUTED`` or ``DENIED``.
    That resolution is an ordinary one-result call: ADR-0173 §13 leaves "a streaming
    twin for ``resume``" undecided, and a park owes no answer to stream.
    An :class:`AssistantError` from any stage is rendered and mapped to a non-zero
    exit code — the adapter surfaces the failure, it does not swallow it. **So is a
    step that ran and failed** (#531): a non-zero exit on a failed step is an
    ordinary adapter responsibility under ADR-0042 §6 once the outcome is
    addressable, and without it a scripted caller reads success from a turn whose
    tool raised.

    The conversation footer is printed **once**, from the last outcome produced: a
    parked turn and the resolution that answers it are two episodes in one
    conversation, and printing the same id twice would read as two.
    """
    streamed = _StreamedReply()
    try:
        settled = await _read_stream(
            engine.converse_streaming(utterance, timeout=timeout, conversation_id=conversation_id),
            into=streamed,
        )
        if settled is None:
            streamed.abandon()
            console.print(
                "[red]That turn's answer ended without a result[/], so I cannot say "
                "what became of it. Nothing here was retried."
            )
            return _EXIT_ERROR
        outcome = settled
        failed = _render_turn(outcome, streamed=streamed)
        step = outcome.step
        routed = outcome.routed
        if step is not None and step.confirmation is not None:
            approved = approver(step.confirmation)
            outcome = await engine.resume(
                step.confirmation.token, approved=approved, timeout=timeout
            )
            failed = _render_turn(outcome)
        elif routed is not None and routed.confirmation is not None:
            # The card is already on screen — `_render_turn` put it there above, which
            # is what makes `--yes` safe (ADR-0073 §5) — so `confirm_operation` reads
            # the answer and renders nothing.
            answered = confirm_operation(routed.confirmation)
            outcome = await engine.resume(
                routed.confirmation.token, approved=answered, timeout=timeout
            )
            failed = _render_turn(outcome)
    except (AssistantError, TransportError) as exc:
        streamed.abandon()
        _render_error(exc)
        return _EXIT_ERROR
    except BaseException:
        # A cancellation is not an error and is not handled here — it is re-raised
        # exactly as it arrived, and ADR-0173 §9 is explicit that abandoning the
        # stream does not abandon the turn. What is owed is the line: the answer is
        # written with no ending so the next chunk can continue it, and
        # `asyncio.CancelledError` and `KeyboardInterrupt` are `BaseException`, so
        # Ctrl-C after `half an ` had been rendered went past the handler above and
        # put the next shell prompt on that same line (#1352). `abandon` is
        # idempotent, so this costs nothing on a path that already settled.
        streamed.abandon()
        raise
    _render_conversation_footer(outcome)
    return _EXIT_ERROR if failed else _EXIT_OK


async def _read_stream(
    stream: AsyncIterator[ReplyChunk | TurnOutcome], *, into: _StreamedReply
) -> TurnOutcome | None:
    """Render the chunks of one streamed turn and return its terminal outcome.

    **The union is resolved by type and the outcome ends the read** (ADR-0173 §4):
    zero or more chunks, then exactly one :class:`TurnOutcome`, then stop. Stopping
    at the outcome rather than reading on is what leaves a peer that kept writing
    unable to add prose after the answer was settled, and :func:`closing_stream`
    turns that early exit into the hang-up §4 makes the caller's obligation. The
    same context manager closes the stream when the iteration raises, and when a
    ``KeyboardInterrupt`` cancels the read part-way through an answer.

    **``None`` is the contract's own impossibility, rendered rather than crashed.**
    §4 has the outcome "always present unless the call raises", and both
    implementations of it read until a terminal frame or fail loudly — so this
    returns ``None`` only for a producer that ended the iteration silently, and the
    caller says so instead of inventing an outcome or letting a traceback out
    (ADR-0042 §7).

    Args:
        stream: What ``converse_streaming`` handed back, un-iterated.
        into: The accumulator the chunks are rendered through.

    Returns:
        The turn's terminal outcome, or ``None`` if the stream ended without one.
    """
    async with closing_stream(stream) as values:
        async for value in values:
            if isinstance(value, ReplyChunk):
                into.take(value)
                continue
            return value
    return None


async def _drive_conversations(engine: AssistantEngine, *, limit: int, offset: int) -> int:
    """Ask the façade for one page of conversations and render it (ADR-0074 §2).

    The adapter relays the page and renders what comes back; it re-orders nothing,
    reads no clock, and cannot show a deleted conversation — the store's stamp is
    what keeps one out, not a filter here.
    """
    try:
        page = await engine.recent_conversations(limit=limit, offset=offset)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_conversations(page, limit=limit, offset=offset)
    return _EXIT_OK


async def _drive_forget_conversation(
    engine: AssistantEngine, conversation_id: str, *, confirm: Callable[[ConversationDigest], bool]
) -> int:
    """Show the conversation's count and span, take the answer, then destroy it.

    Show-then-confirm at the unit the user thinks in (ADR-0074 §8, ADR-0073 §5).
    A refusal is a valid outcome and exits 0. An id naming no conversation this
    surface can show — unknown, or already deleted — is reported and exits non-zero.
    """
    try:
        digest = await engine.conversation(conversation_id)
        if digest is None:
            _render_no_such_conversation(conversation_id)
            return _EXIT_ERROR
        _render_forget_conversation_prompt(digest)
        if not confirm(digest):
            console.print("[dim]Left alone. Nothing was forgotten.[/]")
            return _EXIT_OK
        destroyed = await engine.forget_conversation(digest.id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print("[yellow]Nothing to forget:[/] that conversation was already gone.")
        return _EXIT_ERROR
    console.print("[green]Forgotten.[/] That conversation and everything it recorded are gone.")
    return _EXIT_OK


async def _drive_transcript_search(
    engine: AssistantEngine, query: str, *, limit: int, offset: int
) -> int:
    """Search the archive, then render the hits with the size beside them (ADR-0225 §6, §7).

    **Two calls, and the second is not optional** (§6): the size report is "rendered
    beside every read, unasked", so a surface that skipped it because nothing matched
    would leave the deferred cap's trigger a figure nobody produces, which is the
    ADR-0162 §5 failure §6 exists to avoid.
    """
    try:
        hits = await engine.transcript_search(query, limit=limit, offset=offset)
        size = await engine.transcript_archive_size()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_transcript_notice()
    _render_transcript_hits(hits, limit=limit, offset=offset)
    _render_archive_size(size)
    return _EXIT_OK


async def _drive_transcript_conversation(
    engine: AssistantEngine, conversation_id: str, *, limit: int, offset: int
) -> int:
    """Read one conversation's transcript and render it in the order it was said."""
    try:
        page = await engine.transcript_conversation(conversation_id, limit=limit, offset=offset)
        size = await engine.transcript_archive_size()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_transcript_notice()
    _render_transcript_entries(
        page,
        limit=limit,
        offset=offset,
        empty="No transcript is held under that id. It may never have existed, or you "
        "may have destroyed it already.",
    )
    _render_archive_size(size)
    return _EXIT_OK


async def _drive_transcript_entry(engine: AssistantEngine, address: str) -> int:
    """Read one entry whole and render it, or report that nothing is at that address."""
    try:
        entry = await engine.transcript_entry(address)
        size = await engine.transcript_archive_size()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_transcript_notice()
    if entry is None:
        _render_no_such_transcript_entry(address)
        _render_archive_size(size)
        return _EXIT_ERROR
    _render_transcript_entry(entry)
    _render_archive_size(size)
    return _EXIT_OK


async def _drive_transcript_export(engine: AssistantEngine, *, limit: int, offset: int) -> int:
    """Enumerate the archive and render the page — the export ADR-0225 §7 makes a read."""
    try:
        page = await engine.transcript_entries(limit=limit, offset=offset)
        size = await engine.transcript_archive_size()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_transcript_notice()
    _render_transcript_entries(
        page,
        limit=limit,
        offset=offset,
        empty="The archive holds nothing yet — a conversation puts turns in it.",
    )
    _render_archive_size(size)
    return _EXIT_OK


async def _drive_forget_transcript_entry(
    engine: AssistantEngine, address: str, *, confirm: Callable[[TranscriptEntry | None], bool]
) -> int:
    """Show the turn, take the answer, then destroy the entry (ADR-0225 §5, ADR-0073 §5).

    **The ceremony renders an archive read, so it owes §8's statement and §6's figure
    like any other.** The clause is keyed on rendering rather than on the command's
    name — "every surface that renders any archive read renders the figure it returns
    beside that read, unasked" — and a deletion preview is a read of the entry it is
    about. Dropping either here would put the one rendering a user studies hardest
    outside both obligations.

    **An address the read answers nothing for is still offered**, and that is the
    decision rather than an oversight. ADR-0225 §6 has the destroys reach what the
    reads hide — "a destruction is never refused on the ground that a read would not
    have shown it" — so refusing here would put a turn a finite
    ``transcript_archive_retention`` is hiding permanently beyond the user's reach,
    which is ADR-0004 §6's right made conditional on a horizon. What the prompt owes
    in that case is honesty about what it cannot show, not a refusal.
    """
    try:
        entry = await engine.transcript_entry(address)
        size = await engine.transcript_archive_size()
        _render_transcript_notice()
        _render_forget_transcript_prompt(address, entry)
        _render_archive_size(size)
        if not confirm(entry):
            console.print("[dim]Left alone. Nothing was destroyed.[/]")
            return _EXIT_OK
        destroyed = await engine.forget_transcript_entry(address)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print("[yellow]Nothing to destroy:[/] no transcript was held at that address.")
        return _EXIT_ERROR
    console.print("[green]Destroyed.[/] That turn's transcript is gone.")
    return _EXIT_OK


async def _drive_forget_transcript_conversation(
    engine: AssistantEngine,
    conversation_id: str,
    *,
    confirm: Callable[[tuple[TranscriptEntry, ...]], bool],
) -> int:
    """Show what is held, take the answer, then destroy the conversation's transcript.

    **It renders an archive read, so §8's statement and §6's figure are owed here
    too**, on :func:`_drive_forget_transcript_entry`'s reason.

    Show-then-confirm at the unit the user thinks in (ADR-0225 §5, ADR-0073 §5), and
    the shown page is deliberately **not** claimed to be the whole of what will go:
    the read is paged and the retention hides what the destroy still reaches, so the
    prompt states the scope in words — every turn of this conversation — rather than
    a count it cannot honestly produce.
    """
    try:
        page = await engine.transcript_conversation(conversation_id)
        size = await engine.transcript_archive_size()
        _render_transcript_notice()
        _render_forget_transcript_conversation_prompt(conversation_id, page)
        _render_archive_size(size)
        if not confirm(page):
            console.print("[dim]Left alone. Nothing was destroyed.[/]")
            return _EXIT_OK
        destroyed = await engine.forget_transcript_conversation(conversation_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print(
            "[yellow]Nothing to destroy:[/] no transcript was held under that conversation."
        )
        return _EXIT_ERROR
    console.print(
        f"[green]Destroyed.[/] {destroyed} turn(s) of that conversation's transcript are gone."
    )
    return _EXIT_OK


async def _drive_observe(engine: AssistantEngine, conversation_id: str | None) -> int:
    """Run one observation pass and render what it did (ADR-0077 §8, ADR-0042 §6).

    The adapter conveys the request and renders the engine's
    :class:`~ai_assistant.orchestration.ObservationReport`; it selects no episodes,
    proposes nothing, and authors no memory write — all of that is behind the
    façade (ADR-0042 §6). An :class:`AssistantError` from any stage is rendered and
    mapped to a non-zero exit code.
    """
    try:
        report = await engine.observe(conversation_id=conversation_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_observation(report)
    return _EXIT_OK


async def _drive_questions(engine: AssistantEngine, *, limit: int, offset: int) -> int:
    """Ask the façade for the two question lists and render them (ADR-0078 §8).

    **Two calls, two lists, never merged.** An interrupted question is not answerable,
    so offering it beside the ones that are would present a claim that cannot be
    taken — which is why the façade keeps two enumerations and why this renders two
    sections rather than one table with a status column. They are both printed by one
    command because ADR-0078 §9 makes disposing of a stranded question the user's
    *first* recovery step, and a step behind a flag nobody knows to pass is a step
    nobody takes.

    The adapter re-filters nothing, re-orders nothing and reads no clock: membership
    and order are the store's contract, each row's band was projected in the engine,
    and every instant shown arrived on the DTO.
    """
    try:
        waiting = await engine.questions(limit=limit, offset=offset)
        stranded = await engine.interrupted_questions(limit=limit, offset=offset)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_questions(waiting, stranded, limit=limit, offset=offset)
    return _EXIT_OK


async def _drive_answer(engine: AssistantEngine, question_id: str, *, accept: bool) -> int:
    """Relay one answer and render what it did (ADR-0078 §9, ADR-0042 §6).

    The adapter conveys the user's yes/no and renders the engine's outcome; it authors
    no memory write, mints no authority and reaches no subsystem. A question that is
    not open is reported and exits non-zero, exactly as an id naming no belief does.
    """
    try:
        outcome = await engine.answer(question_id, accept=accept)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    return _render_answer(outcome)


async def _drive_forget_question(engine: AssistantEngine, question_id: str) -> int:
    """Destroy one question and report whether anything was there (ADR-0078 §9)."""
    try:
        destroyed = await engine.forget_question(question_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print("[yellow]Nothing to forget:[/] no question has that id.")
        return _EXIT_ERROR
    console.print(
        "[green]Forgotten.[/] That question is destroyed. If an answer to it was "
        "already in flight, check 'assistant beliefs' — I cannot tell you whether "
        "that write landed — and use 'assistant learn' again if the correction is "
        "missing."
    )
    return _EXIT_OK


async def _drive_learn(engine: AssistantEngine, event: FeedbackEvent) -> int:
    """Submit one feedback event and render what memory did with it (ADR-0042 §3, §6).

    The correction leg of the pipeline: the adapter conveys the feedback and renders
    the engine's :class:`~ai_assistant.orchestration.LearnOutcome` summary; it
    authors no memory write and reaches no subsystem (ADR-0042 §6). An
    :class:`AssistantError` from any stage is rendered and mapped to a non-zero exit
    code — the adapter surfaces the failure, it does not swallow it.
    """
    try:
        outcome = await engine.learn(event)
        _render_learn(outcome)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    return _EXIT_OK


async def _drive_sources(engine: AssistantEngine) -> int:
    """Ask the hub what may be granted and render it (ADR-0102 §1)."""
    try:
        offered = await engine.grantable_sources()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_sources(offered)
    return _EXIT_OK


async def _drive_grant(
    engine: AssistantEngine,
    source: str,
    *,
    scope: list[GrantScope],
    confirm: Callable[[GrantableSource], bool],
) -> int:
    """Enumerate, show, take the answer, and only then grant (ADR-0102 §6).

    **The enumeration is not an optimisation and skipping it is not permitted.**
    ADR-0102 §6's third clause obliges a client to render the source's configured
    location and take an explicit act before it sends ``grant``, and "a client that
    cannot show the user the location does not send ``grant``". Nothing on the wire
    distinguishes a client that obeyed from one that did not (ADR-0098 §5), so this
    is the only place the clause can live — and it is why the flow is
    enumerate-then-grant rather than a single call.

    A source the enumeration does not carry is therefore **not granted from here**,
    whatever the reason it is missing: no such source, a reader whose declared name
    is inadmissible, or a configured location with no UTF-8 encoding. All three
    leave nothing to show, and §6 fails closed rather than granting unseen.

    The source is relayed **untouched** — never stripped — because whether it names
    a held reader is the hub's question and ADR-0102 §2 makes an exact comparison
    the whole contract of that argument.
    """
    try:
        offered = await engine.grantable_sources()
        chosen = next((one for one in offered if one.source == source), None)
        if chosen is None:
            _render_no_such_source(source, offered)
            return _EXIT_ERROR
        _render_grant_prompt(chosen, scope)
        if not confirm(chosen):
            console.print("[dim]Left alone. Nothing was granted.[/]")
            return _EXIT_OK
        # Relayed as the user typed it, and as the enumeration returned it: they are
        # equal by the check above, so this is the declared identity either way.
        recorded = await engine.grant(chosen.source, scope=scope)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    withdrawal = (
        f"Withdraw it any time with 'assistant revoke {_argument(recorded.source)}'."
        if _is_pasteable(recorded.source)
        else f"Withdraw it any time with 'assistant revoke'. {_uncopyable('Its name')}"
    )
    _print_hint(
        f"[green]Granted.[/] I may now read [bold]{_safe(recorded.source)}[/] for "
        f"{_scope_phrase(recorded.scope)}. {withdrawal}"
    )
    return _EXIT_OK


async def _drive_revoke(engine: AssistantEngine, source: str) -> int:
    """Relay one revocation and say exactly what it did — and did not do.

    The wording is load-bearing (ADR-0102 §9). "Your calendar is no longer being
    read" is the sentence a person writes and it overclaims: what is true is that no
    *further* read starts and nothing an in-flight read produces is used. ADR-0097
    §5a declines to promise more, so neither does this. And ``None`` is not silence
    about it either — it means there was no live grant when the call ran, which says
    nothing about reads, so rendering it as "nothing was happening" would invent the
    same overclaim from the other side.
    """
    try:
        withdrawn = await engine.revoke(source)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if withdrawn is None:
        console.print(
            "[yellow]Nothing to withdraw:[/] no live grant covers that source. "
            "(That is about the grant, not about any read — see 'assistant grants' "
            "for what was granted and withdrawn.)"
        )
        return _EXIT_ERROR
    console.print(
        f"[green]Withdrawn.[/] I will start no further read of "
        f"[bold]{_safe(withdrawn.source)}[/], and nothing a read still running "
        f"produces will be used. What I already believe from it is untouched — see "
        f"'assistant beliefs'."
    )
    return _EXIT_OK


async def _drive_grants(engine: AssistantEngine, *, limit: int) -> int:
    """Read the grant record and render it, newest first (ADR-0097 §4)."""
    try:
        recorded = await engine.recent_grants(limit=limit)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_grants(recorded, limit=limit)
    return _EXIT_OK


async def _drive_standing(engine: AssistantEngine) -> int:
    """Ask the hub what the user currently authorises and render it (ADR-0139 §2).

    **One call and no second one**, which is the whole of ADR-0139 §1 as it reaches
    a client: this adapter does not fetch ``grantable_sources`` to annotate the set,
    does not drop a record because no held reader declares its source, and does not
    merge the two answers. A grant on a source the hub no longer builds is exactly
    what this command exists to show, and each of those moves would hide it again.

    Nothing is re-derived either. Liveness was computed hub-side from the ``revokes``
    relation (ADR-0097 §4); a client that answered this by walking ``recent_grants``
    would report a withdrawn grant as live the moment a clock moved backwards, which
    is what ADR-0102 §3 forbids and what this operation exists to make unnecessary.
    """
    try:
        standing = await engine.standing_grants()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_standing(standing)
    return _EXIT_OK


def _outcome_of(exc: Exception) -> _ActOutcome:
    """Classify what one failed act of an amendment is known to have done.

    A **typed refusal** is the hub having received the request and declined it, so
    nothing was written: known not to have landed. A **transport failure** is the
    answer having been lost, and the hub may well have committed first — ADR-0084
    §3 keeps the two events distinct precisely because they are not the same thing,
    and here the difference decides what a user is told.

    :class:`~ai_assistant.core.errors.OversizedValueError` is a typed refusal that
    is nonetheless **unknown**, and it is the one worth stating. On a mutating call
    the result is measured *after* the work has committed (ADR-0085 §8e, #570), so
    an oversized ``grant`` result means the record stands and could not be returned
    — while an oversized *argument* is refused before any I/O and did not land. A
    caller cannot tell those apart from the exception, and ADR-0139 §4's third
    outcome exists for exactly this: report what is known rather than pick.
    """
    if isinstance(exc, TransportError | OversizedValueError):
        return _ActOutcome.UNKNOWN
    return _ActOutcome.NOT_LANDED


async def _state_after(engine: AssistantEngine, source: str) -> SourceGrant | None | _Unread:
    """Re-read what ``source`` is currently granted for, or report it unread.

    **ADR-0139 §4's third clause is why this exists at all**: no surface may infer a
    source's state from an act's outcome, and this is the read that states it
    instead. The inference is tempting and wrong in both directions — a ``grant``
    refused with ``InvalidGrantError`` can mean *another client granted the source
    in between* (ADR-0102 §5), so "it is now ungranted" is false in the very case
    that produced the refusal.

    A failed read leaves the state **unread** rather than assumed. That is the
    honest answer and it is also the only safe one: the alternative is a client
    that says "not granted" because it could not ask.
    """
    try:
        standing = await engine.standing_grants()
    except AssistantError, TransportError:
        return _UNREAD
    return next((record for record in standing if record.source == source), None)


async def _drive_amend(
    engine: AssistantEngine,
    source: str,
    *,
    scope: list[GrantScope],
    confirm: Callable[[GrantableSource], bool],
) -> int:
    """Withdraw one grant and make another, reporting what each act did (ADR-0139 §4).

    **The two acts are the client's, and that is the design rather than a
    limitation.** ADR-0102 §1 refuses a compound hub operation and ADR-0139 §4
    re-refuses it, on the ground that a compound call "would hide the intermediate
    state inside the hub, where the client could not report it". Composing them here
    is what puts that state somewhere a person can be told about it.

    **The decision comes first and nothing is withdrawn in order to ask** (§4's
    sixth clause). The scope arrives on the command line and the confirmation is
    taken before the revocation is sent, so a user who hesitates, or closes the
    terminal, has not withdrawn their grant by starting to think. It also discharges
    §5: the enumeration is fetched and the location rendered before any ``grant``
    goes out, and a source the enumeration does not carry is not amended from here
    — there is nothing to show, and §6 fails closed rather than granting unseen.

    **A revocation whose outcome is not known stops the amendment** (§4's fourth
    clause). Sending the grant anyway would buy an answer nobody can read: a refusal
    is equally consistent with the revocation not having landed and with another
    client having granted in between, so the inference is the one §4's third clause
    forbids. One read settles it; a second write does not.

    A revocation **known** not to have landed stops it too. Nothing obliges that,
    and it is the conservative reading of the same clause: what is known is that the
    hub declined, and following a declined withdrawal with a grant is a second write
    made on no better information than the first refusal gave.
    """
    try:
        offered = await engine.grantable_sources()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    chosen = next((one for one in offered if one.source == source), None)
    if chosen is None:
        _render_unamendable_source(source, offered)
        return _EXIT_ERROR
    _render_amend_prompt(chosen, scope)
    if not confirm(chosen):
        console.print("[dim]Left alone. Nothing was withdrawn and nothing was granted.[/]")
        return _EXIT_OK

    try:
        withdrawn = await engine.revoke(chosen.source)
    except asyncio.CancelledError:
        # §4's fifth clause, and ``CancelledError`` is a ``BaseException`` — the
        # natural ``except Exception`` above would not see it, and a client written
        # that way exits without reporting anything. Reporting is all that happens
        # here: no further call is started, and the cancellation still leaves.
        _render_act("withdrawal", _ActOutcome.UNKNOWN)
        _render_unread(chosen.source)
        raise
    except (AssistantError, TransportError) as exc:
        outcome = _outcome_of(exc)
        _render_act("withdrawal", outcome, detail=_leaf_messages(exc))
        _render_amendment_stopped(outcome)
        _render_state(chosen.source, await _state_after(engine, chosen.source))
        return _EXIT_ERROR
    _render_act("withdrawal", _ActOutcome.LANDED, withdrew=withdrawn is not None)

    try:
        await engine.grant(chosen.source, scope=scope)
    except asyncio.CancelledError:
        _render_act("grant", _ActOutcome.UNKNOWN)
        _render_unread(chosen.source)
        raise
    except (AssistantError, TransportError) as exc:
        _render_act("grant", _outcome_of(exc), detail=_leaf_messages(exc))
        _render_state(chosen.source, await _state_after(engine, chosen.source))
        return _EXIT_ERROR
    _render_act("grant", _ActOutcome.LANDED)
    _render_state(chosen.source, await _state_after(engine, chosen.source))
    return _EXIT_OK


async def _drive_notifications(engine: AssistantEngine, *, limit: int, offset: int) -> int:
    """Ask the façade for one page of held notifications and render it (ADR-0130 §7).

    The adapter relays the page and renders what comes back. It re-rules nothing,
    re-orders nothing and re-filters nothing: the ruling, the condition that decided
    it and the whole set it is waiting on all arrived on each record, and every
    instant shown is one the engine recorded.

    **The one clock reading is taken here, once per page, and is an argument
    everywhere below it.** ADR-0130 §7 has an expired record stay enumerable and
    render *as expired*, and no field on the record says which side of that line it is
    on — so the reading is the missing half of a comparison the core type performs
    (:func:`_render_notification`). Taking it once is what keeps two rows of one page
    from being judged at two instants, and passing it down is what keeps every
    renderer a pure function of what it was handed.
    """
    try:
        page = await engine.notifications(limit=limit, offset=offset)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_notifications(page, now=_utcnow(), limit=limit, offset=offset)
    return _EXIT_OK


async def _drive_dismiss_notification(engine: AssistantEngine, notification_id: str) -> int:
    """Dismiss one notification and report whether there was one to dismiss (§7, §9).

    ``False`` covers four different states — no such id, and one already dismissed,
    expired or dropped — and the message says so rather than picking one, because the
    façade returns a single boolean and guessing between them here would be inventing
    a diagnosis this process cannot make.
    """
    try:
        dismissed = await engine.dismiss_notification(notification_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not dismissed:
        console.print(
            "[yellow]Nothing to dismiss:[/] no notification with that id is still "
            "outstanding. It may never have existed, or it may already have been "
            "dismissed, expired, or ruled out — 'assistant notifications' lists what "
            "I am holding."
        )
        return _EXIT_ERROR
    console.print(
        "[green]Dismissed.[/] It will not reach you, and the record is still there — "
        "'assistant forget-notification' destroys it. If I notice that again it is a "
        "new notification rather than a duplicate."
    )
    return _EXIT_OK


async def _drive_forget_notification(engine: AssistantEngine, notification_id: str) -> int:
    """Destroy one notification and report whether anything was there (ADR-0130 §9)."""
    try:
        destroyed = await engine.forget_notification(notification_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        console.print("[yellow]Nothing to forget:[/] no notification has that id.")
        return _EXIT_ERROR
    console.print(
        "[green]Forgotten.[/] That notification is destroyed — it is in no export. "
        "Because its record is also what stopped me raising the same thing twice, "
        "the next time I notice it, it is new to me."
    )
    return _EXIT_OK


async def _drive_notification_settings(engine: AssistantEngine) -> int:
    """Read the three standing settings and render them (ADR-0130 §6)."""
    try:
        preferences = await engine.notification_preferences()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_notification_settings(preferences)
    return _EXIT_OK


async def _drive_tune(engine: AssistantEngine, asked: _Tuning) -> int:
    """Read the standing settings, substitute what the user named, and write back.

    **Read-adjust-write is the flow the contract prescribes**, not one this adapter
    invented: :meth:`AssistantEngine.set_notification_preferences` writes the whole
    value and says in terms that "a caller changing one setting reads, adjusts and
    writes back", together with the consequence — no version token, no conflict
    detection, and the later of two racing writes wins. A CLI that instead demanded
    every setting on every invocation would make the one act ADR-0130 §6 requires of
    the user (raising a class) cost them the rest of their settings to perform.

    Nothing is decided here. The axes the user named are substituted and the rest are
    relayed verbatim; which held records the write then re-arms, and what a class's
    reach means for any of them, is the engine's ruling (§5, §6) and this module
    neither computes nor predicts it. The resulting settings are rendered from what
    the *store* handed back rather than from what was sent, so what is shown is what
    is in force.
    """
    try:
        current = await engine.notification_preferences()
        written = await engine.set_notification_preferences(_tuned(current, asked))
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    console.print("[green]Tuned.[/] These are the settings in force now.\n")
    _render_notification_settings(written)
    _render_reach_notice(current, asked)
    return _EXIT_OK


async def _drive_connect(
    engine: AssistantEngine, identity: str, *, read_credential: Callable[[], str]
) -> int:
    """Show the identity, take the credential, connect, and report the outcome.

    **The display is not a courtesy and skipping it is not permitted** (ADR-0151
    §5): "every client that accepts an identity displays it to the user as part of
    the act", and nothing on the wire distinguishes a client that did from one that
    did not (ADR-0098 §5). It is shown *before* the credential is asked for, which
    is the ordering that makes it useful — ADR-0149 §4's third answer to a
    credential pasted into the identity field is precisely that the value is seen,
    and a client that rendered it afterwards would show it once the secret had
    already been typed into the field beside it.

    Everything after the call is ADR-0151 §7's classification, and the one thing
    this function may not do is report the act as having changed nothing. Five of
    the six outcomes are the exception classes; the sixth is the return.
    """
    _render_connection_intent(identity)
    try:
        credential = _credential(read_credential())
    except ValueError as exc:
        _render_unusable_credential(exc)
        return _EXIT_ERROR

    try:
        connected = await engine.connect_account(identity=identity, credential=credential)
    except asyncio.CancelledError:
        # ADR-0151 §7's cancellation clause: a cancelled act leaves the same outcome
        # the partial classes describe, the client says so **without the reference
        # and without starting a call to obtain one**, and the ``CancelledError``
        # still leaves (ADR-0060). ``CancelledError`` is a ``BaseException``, so the
        # handler below would not see it.
        _render_cancelled_act("connection")
        _render_connections_unread()
        raise
    except (AssistantError, TransportError) as exc:
        return await _report_provisioning_failure(engine, "connection", exc, reference=None)
    _render_connected("Connected", connected)
    return _EXIT_OK


async def _drive_reconnect(
    engine: AssistantEngine,
    reference: str,
    *,
    identity: str,
    read_credential: Callable[[], str],
) -> int:
    """Show the identity, take the credential, re-provision, and report the outcome.

    :func:`_drive_connect` with two differences, both of them ADR-0151's. The
    reference is the caller's, so every refusal has one to name and every unread
    state has one to read (§2a, §7). And two further outcomes are reachable that a
    fresh connection cannot produce — a reference the store does not hold, and a
    losing compare-and-swap — which is the whole reason §1 refused to fold the two
    operations into one method with an optional reference.
    """
    _render_connection_intent(identity, reference=reference)
    try:
        credential = _credential(read_credential())
    except ValueError as exc:
        _render_unusable_credential(exc)
        return _EXIT_ERROR

    try:
        connected = await engine.reprovision_account(
            reference, identity=identity, credential=credential
        )
    except asyncio.CancelledError:
        _render_cancelled_act("re-provisioning")
        _render_connection_unread(reference)
        raise
    except (AssistantError, TransportError) as exc:
        return await _report_provisioning_failure(
            engine, "re-provisioning", exc, reference=reference
        )
    _render_connected("Re-provisioned", connected)
    return _EXIT_OK


async def _drive_disconnect(engine: AssistantEngine, reference: str) -> int:
    """Relay one disconnection and say exactly what it did — and did not do.

    Three answers, and ADR-0151 §8 rules each of them. A record is the live one that
    was removed. A ``None`` says **one** thing — no live record was removed by this
    call — and is not a report of a disconnection, not a confirmation that a
    credential was deleted, and not a statement that the reference does not exist. A
    :class:`~ai_assistant.core.errors.ResidualCredentialError` means the removal
    *landed* and a deletion did not, so it is reported as a disconnection whose
    credential deletion is incomplete and never as a failed disconnection — which is
    why it is caught above the general handler rather than through it.
    """
    try:
        removed = await engine.disconnect_account(reference)
    except asyncio.CancelledError:
        _render_cancelled_act("disconnection")
        _render_connection_unread(reference)
        raise
    except ResidualCredentialError as exc:
        _render_residual_credential(
            "Disconnected. No live record names any credential for that reference any more.",
            exc,
            reference=reference,
        )
        return _EXIT_ERROR
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        _render_connection_state(reference, await _connection_state(engine, reference))
        return _EXIT_ERROR
    if removed is None:
        _render_nothing_removed(reference)
        return _EXIT_ERROR
    _render_disconnected(removed)
    return _EXIT_OK


async def _drive_connections(engine: AssistantEngine) -> int:
    """Ask the hub what is connected now and render it whole (ADR-0151 §9).

    **One call and no second one.** This adapter does not annotate the set against
    what the hub can currently offer, does not drop a record whose integration is
    not built, and does not merge in ``recent_connection_acts``: a connection the
    hub can do nothing with is exactly what this command exists to show, and each of
    those moves would hide it again. Nothing is re-derived either — a reference's
    state is the store's answer, and ADR-0151 §9 forbids reading one off the history.
    """
    try:
        connected = await engine.connected_accounts()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_connections(connected)
    return _EXIT_OK


async def _drive_connection_acts(engine: AssistantEngine, *, limit: int) -> int:
    """Read what was done to connections and render it in the store's own order."""
    try:
        acts = await engine.recent_connection_acts(limit=limit)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_connection_acts(acts, limit=limit)
    return _EXIT_OK


async def _drive_decisions(engine: AssistantEngine, *, limit: int) -> int:
    """Read the bounded listing and render it in the operation's own order.

    The order is the **engine's** guarantee (ADR-0186 §2) — ``decided_at``
    descending, ties broken by ``id`` ascending — so nothing here sorts, and
    nothing here filters: a consumer wanting a subset selects it from what the
    operation returned, and an adapter selecting for the user would be the business
    logic golden rule 3 keeps out of this layer.
    """
    try:
        recorded = await engine.recent_decisions(limit=limit)
        _refuse_a_page_this_surface_cannot_state(recorded)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_decisions(recorded, limit=limit)
    return _EXIT_OK


def _refuse_a_page_this_surface_cannot_state(recorded: tuple[PermissionDecision, ...]) -> None:
    """Run ADR-0193 §11's dispatch over the whole page before a byte is printed.

    **Ahead of the rendering rather than inside it**, so the refusal is a refusal
    and not a half-drawn listing: ADR-0186 §7 says a surface that cannot render a
    row whole renders *fewer rows*, not partial ones, and a page half printed under
    an error message is exactly the partial rendering that clause is about. The
    existing boundary in :func:`_drive_decisions` then reports it, as it reports an
    unreadable trail — a refusal reaches the user as itself and no row is invented.

    **It is :func:`_authorisation_line` itself and not a second copy of its rule**,
    which is the whole point of calling it here: a check that restated the three
    conditions would be a second spelling to keep in step with the first, and the
    failure would be a page that passed the check and then raised mid-render.

    Args:
        recorded: The page the operation returned, in its own order.

    Raises:
        InvalidResolutionError: If any ``ALLOW`` on the page satisfies none of
            §11's three conditions.
    """
    for decision in recorded:
        if decision.ruling.outcome is PermissionOutcome.ALLOW:
            _authorisation_line(decision)


async def _drive_export_decisions(engine: AssistantEngine, *, artifact: TextIO) -> int:
    """Read the whole trail and write ADR-0186 §9's document to ``artifact``.

    **Whole or nothing.** ``export_decisions`` raises rather than truncating when
    the trail outgrows the contract limit (ADR-0085 §8c), and that refusal is
    rendered as an error on standard error with **no** document written — a partial
    artifact that looked complete is the one outcome §9 rules out, and it is the one
    a helpful adapter would produce.
    """
    try:
        recorded = await engine.export_decisions()
    except (AssistantError, TransportError) as exc:
        _render_error(exc, to_stderr=True)
        return _EXIT_ERROR
    artifact.write(_decisions_artifact(recorded))
    artifact.flush()
    return _EXIT_OK


def _decisions_artifact(recorded: tuple[PermissionDecision, ...]) -> str:
    """ADR-0186 §9's document: the decisions' own JSON projections, and nothing else.

    **Faithful, which is a statement about keys.** Each row is its own
    ``model_dump(mode="json")`` and this adds no key, removes none, renames none,
    reorders none for presentation and annotates none — so the array re-validates
    as ``tuple[PermissionDecision, ...]``, whose models set ``extra="forbid"``. A
    friendly ``"origin": "not recorded"`` marker beside the members would make the
    export fail its own re-validation and stop being an export; the *words* for that
    state are :func:`_recorded_origin_line`'s job on the listing, not this one's
    (ADR-0184 §3, ADR-0186 §9).

    **Indentation is not a key.** The whitespace is chosen so a person can read what
    they exported, and it changes no member, no order and no value; ``json.dumps``
    emits the array in the order the operation returned, which is ADR-0186 §2's.

    Args:
        recorded: Every decision the trail holds, in the operation's order.

    Returns:
        One JSON document, newline-terminated so it is a well-formed text stream.
    """
    return json.dumps([decision.model_dump(mode="json") for decision in recorded], indent=2) + "\n"


async def _drive_reads(engine: AssistantEngine, *, limit: int) -> int:
    """Read the bounded listing of read attempts and render it in the operation's order.

    The order is the **engine's** guarantee and is this store's own rather than
    ADR-0186 §2's: ``recent_reads`` answers newest-*recorded* first, because
    ``SourceReadTrail.recent`` is ordered "by recording order, reversed — never by
    ``checked_at``" (ADR-0185 §6). So nothing here sorts — and nothing here *could*
    sort correctly, since a record carries no sequence number, its ``id`` is
    caller-minted and unordered, and its ``checked_at`` is caller-supplied. Nothing
    here filters either: a consumer wanting a subset selects it from what the
    operation returned, and an adapter selecting for the user would be the business
    logic golden rule 3 keeps out of this layer.
    """
    try:
        recorded = await engine.recent_reads(limit=limit)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_reads(recorded, limit=limit)
    return _EXIT_OK


async def _drive_export_reads(engine: AssistantEngine, *, artifact: TextIO) -> int:
    """Read the whole trail and write ADR-0186 §9's document to ``artifact``.

    **Whole or nothing**, :func:`_drive_export_decisions`' clause over the store
    that prunes. ``export_reads`` raises rather than truncating when the trail
    outgrows the contract limit (ADR-0085 §8c), and that refusal is rendered as an
    error on standard error with **no** document written. "Whole" is the horizon
    the store still holds and never the history (ADR-0185 §9), which is stated in
    the command's own words rather than annotated onto the artifact: a marker key
    would stop the document re-validating and stop it being an export.
    """
    try:
        recorded = await engine.export_reads()
    except (AssistantError, TransportError) as exc:
        _render_error(exc, to_stderr=True)
        return _EXIT_ERROR
    artifact.write(_reads_artifact(recorded))
    artifact.flush()
    return _EXIT_OK


def _reads_artifact(recorded: tuple[SourceReadRecord, ...]) -> str:
    """ADR-0186 §9's document over the read trail: the records' own projections.

    **Faithful, which is a statement about keys.** Each row is its own
    ``model_dump(mode="json")`` and this adds no key, removes none, renames none,
    reorders none for presentation and annotates none — so the array re-validates
    as ``tuple[SourceReadRecord, ...]``, whose model sets ``extra="forbid"``. In
    particular the horizon is **not** annotated onto the document: a
    ``"complete": false`` marker beside the members would fail that re-validation
    and stop the export being one. ``assistant export-reads``' own words are where
    the horizon is stated, exactly as ADR-0186 §9 puts the words for an unrecorded
    origin on ``assistant decisions`` rather than in the artifact.

    **Not folded together with** :func:`_decisions_artifact`, and the reason is the
    return annotation rather than the two-line body. The type is what says which
    store this document is a faithful copy *of*, and it is what
    ``tests/interfaces/test_cli.py``'s walk over this module reads to pin where a
    recorded ruling may reach; a shared helper taking a sequence of models would
    make both claims unstatable.

    Args:
        recorded: Every record the trail still holds, in the operation's order.

    Returns:
        One JSON document, newline-terminated so it is a well-formed text stream.
    """
    return json.dumps([record.model_dump(mode="json") for record in recorded], indent=2) + "\n"


async def _drive_invocations(engine: AssistantEngine, *, limit: int) -> int:
    """Read the bounded listing of invocation rows and render it in the operation's order.

    The order is the **engine's** guarantee (ADR-0192 §4) — the row's
    ``recorded_at`` descending, ties broken by the row's ``id`` ascending — so
    nothing here sorts. Nothing here filters either, and nothing here **pairs**: a
    claim and the completion that names it are two rows of one attempt, and joining
    them would be the second read across two answers §4 forbids a surface making
    (and the business logic golden rule 3 keeps out of this layer).
    """
    try:
        recorded = await engine.recent_invocations(limit=limit)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_invocations(recorded, limit=limit)
    return _EXIT_OK


async def _drive_spend(engine: AssistantEngine) -> int:
    """Read both period totals and render them in the operation's order (ADR-0194 §6).

    The order is the **ledger's** guarantee — ``CALENDAR_DAY`` then
    ``CALENDAR_MONTH`` — so nothing here sorts, filters or looks an entry up by its
    period. Nothing here computes either, and nothing here reads a clock or a zone:
    every figure and every boundary arrived on the value, which is golden rule 3 and
    ADR-0194 §5's reason for carrying resolved offsets rather than a zone name.

    A transport failure renders as itself. ``HubUnavailableError`` and
    ``ProtocolError`` reach this frame unwrapped (ADR-0194 §6), and rendering one as
    an indeterminate budget would tell a user a fact about their spend that nothing
    measured.
    """
    try:
        totals = await engine.spend_totals()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_spend(totals)
    return _EXIT_OK


async def _drive_export_invocations(engine: AssistantEngine, *, artifact: TextIO) -> int:
    """Read every invocation row and write ADR-0186 §9's document to ``artifact``.

    **Whole or nothing**, :func:`_drive_export_decisions`' clause over the third
    pair. ``export_invocations`` raises rather than truncating when the trail
    outgrows the contract limit (ADR-0085 §8c, ADR-0192 §4), and that refusal is
    rendered as an error on standard error with **no** document written — a partial
    artifact that looked complete is the one outcome ruled out, and it is the one a
    helpful adapter would produce.
    """
    try:
        recorded = await engine.export_invocations()
    except (AssistantError, TransportError) as exc:
        _render_error(exc, to_stderr=True)
        return _EXIT_ERROR
    artifact.write(_invocations_artifact(recorded))
    artifact.flush()
    return _EXIT_OK


def _invocations_artifact(recorded: tuple[RecordedInvocation, ...]) -> str:
    """The document over the invocation trail: the rows' own JSON projections.

    **Faithful, which is a statement about keys.** Each row is its own
    ``model_dump(mode="json")`` and this adds no key, removes none, renames none,
    reorders none for presentation and annotates none — so the array re-validates
    as ``tuple[RecordedInvocation, ...]``, whose models set ``extra="forbid"``. In
    particular an unset ``failure_kind`` on a completion is rendered as ``null``
    and never annotated with a friendly marker: what "no kind was reported" means
    is :func:`_invocation_failure_kind`'s job on the listing, exactly as ADR-0186
    §9 puts the words for an unrecorded origin on ``assistant decisions`` rather
    than in the artifact.

    **What the document does not carry is the row's own doing** (ADR-0192 §2). No
    recipient, account, endpoint or destination is in it, because none is in the
    record — the keys are the invocation's own plus the three the store's join
    adds, and the join adds a tool identifier, a capability and a boolean.

    **Not folded together with** :func:`_decisions_artifact` **or**
    :func:`_reads_artifact`, and the reason is those two's: the return annotation
    is what says which store this document is a faithful copy *of*, and a shared
    helper taking a sequence of models would make all three claims unstatable.

    Args:
        recorded: Every invocation row the trail holds, in the operation's order.

    Returns:
        One JSON document, newline-terminated so it is a well-formed text stream.
    """
    return json.dumps([row.model_dump(mode="json") for row in recorded], indent=2) + "\n"


def _partial_reference(exc: BaseException) -> str | None:
    """The reference an error names, where its class carries one (ADR-0151 §2a).

    Three classes do, and each is an outcome in which the act *partly landed* — the
    state a user has to be able to name in order to act on it. After
    ``connect_account`` it is the only handle they will ever have, because §3 minted
    it inside the act and no result came back.

    An **empty** member is not an absent one: ADR-0085 §10a nulls ``details`` before
    it truncates a message, so a reduced delivery reconstructs the class with the
    default and the handle is genuinely lost. That is reported as a loss rather than
    rendered as an empty reference, which is why this returns ``None`` for it.

    Args:
        exc: The failure the act raised.

    Returns:
        The reference, or ``None`` where the class carries none or lost it.
    """
    match exc:
        case (
            IncompleteProvisioningError()
            | ProvisioningOutcomeUnknownError()
            | ResidualCredentialError()
        ):
            return exc.reference or None
        case _:
            return None


def _state_is_known(exc: BaseException) -> bool:
    """Whether a refusal settles the reference's state without a read (ADR-0151 §7).

    Two of the seven classes do, and both are refusals that never reached an act:
    :class:`~ai_assistant.core.errors.UnusableIdentityError` is raised locally before
    any I/O, and :class:`~ai_assistant.core.errors.UnknownConnectionError` is refused
    before the first write. Every other outcome on this surface leaves the state
    **unread**, which ADR-0151 §7 says is resolved by reading ``connected_accounts``
    and never by re-running the act — so a client that treated a refusal as an answer
    about the store would be making the inference §7 exists to forbid.

    Args:
        exc: The failure the act raised.

    Returns:
        Whether the reference's state follows from the class alone.
    """
    return isinstance(exc, UnusableIdentityError | UnknownConnectionError)


async def _connection_state(
    engine: AssistantEngine, reference: str
) -> ConnectedAccount | None | _Unread:
    """Re-read one reference's live record, or report it unread (ADR-0151 §7).

    :func:`_state_after`'s shape on the connection surface, and it exists for the
    same clause one act over: no surface may infer a reference's state from an act's
    outcome, and this is the read that states it instead. The inference is wrong in
    both directions here — an ``IncompleteProvisioningError`` asserts nothing about
    the live record, because a later act may have displaced this one — so the answer
    comes from the store or it is withheld.

    A failed read leaves the state **unread** rather than assumed, which is the only
    safe answer: the alternative is a client that says "nothing is connected" because
    it could not ask.
    """
    try:
        connected = await engine.connected_accounts()
    except AssistantError, TransportError:
        return _UNREAD
    return next((record for record in connected if record.reference == reference), None)


async def _report_provisioning_failure(
    engine: AssistantEngine, act: str, exc: Exception, *, reference: str | None
) -> int:
    """Report one failed provisioning act, then state the reference from a read.

    The two halves are kept apart deliberately, and it is ADR-0151 §7's design
    rather than this function's: an act's outcome is a fact about *that act*, and a
    reference's state is a fact about the store. Only the second is answered by a
    read, and no client derives either from the other.

    A reference the *error* names outranks the one the call carried, because they
    can differ in exactly one direction that matters: after ``connect_account``
    there is no supplied reference at all, and the minted one exists only on the
    error.

    Args:
        engine: The hub, for the read that states the reference's state.
        act: What is being reported, opening each sentence.
        exc: The failure.
        reference: The reference the call carried, where it carried one.

    Returns:
        The process exit code, which is always a failure.
    """
    named = _partial_reference(exc) or reference
    _render_provisioning_outcome(act, exc, reference=named)
    if _state_is_known(exc):
        return _EXIT_ERROR
    if named is None:
        _render_connections_unread()
        return _EXIT_ERROR
    _render_connection_state(named, await _connection_state(engine, named))
    return _EXIT_ERROR


def _render_reach_notice(current: NotificationPreferences, asked: _Tuning) -> None:
    """Say what raising or silencing a class does to what is *already* held (§6).

    **Said in the future tense, never the past.** ADR-0130 §6's write is atomic with a
    ``reconsider_at`` stamp and stops there — "the existing job picks them up on its
    next run" — and §5 makes that floor a floor, since "a late reconsideration is not
    a fault". A record is therefore still ``HOLD`` as this prints, and claiming it had
    already been re-ruled would have the user who raised a class read the silence that
    follows as the act having failed, on the one surface built because that act had no
    door at all (#979).

    **The ``interrupt`` line is qualified a second time**, because reach is not the
    only condition (§5): a held record that named no moment it stops mattering re-holds
    on ``PERISHABLE``, which §6 says "is reached by no setting", so for those the sweep
    changes nothing whenever it runs.

    **And no sweep is announced where the reach did not move** (#985). §6 re-arms a held
    record whose failed conditions hold "a condition that change could remove", so a
    write restating the reach already in force removes nothing and re-arms nothing — a
    record held only on ``QUIET_WINDOW`` or ``BUDGET`` sits exactly where it was, and
    announcing a sweep there is a claim about the store that is false.

    **The sentence that replaces it makes no claim about the store either**, and that
    is deliberate rather than terse. ``current`` is a *pre-write* read, and the contract
    it was taken under has no version token and no conflict detection: a second client
    may write between the read and the write, in which case the delta the store computes
    is not the delta seen here. So the replacement reports only the two things this
    process knows for certain — what its own read held, and what it therefore asked for
    — and leaves every statement about held records to the branches that were already
    making one. Where that residual staleness bites the *other* two lines is #1019,
    whose remedy is a contract that returns what the write re-armed rather than better
    guessing here.

    Naming *which* records were re-armed would be the opposite failure: a copy of §6's
    rule in an adapter, which is the business logic golden rule 3 keeps out.

    Args:
        current: The settings as this process read them, before the write.
        asked: What the user named, parsed.
    """
    if asked.notification_class is None or asked.reach is None:
        return
    if asked.reach is NotificationReach.HOLD:
        # Silent whether it moved or not, and for one reason: lowering a class to
        # `hold` can only *add* a failed condition, never remove one, so §6 re-arms
        # nothing on account of it and there is no consequence to announce.
        return
    if current.reach_for(asked.notification_class) is asked.reach:
        console.print(
            "\n[dim]That class was already reaching you exactly that far in the settings "
            "I read, so this asked for no change to it.[/]"
        )
    elif asked.reach is NotificationReach.INTERRUPT:
        console.print(
            "\n[dim]Anything of that class I am already holding is now due to be "
            "looked at again, on my next sweep rather than this instant — so one that "
            "named a moment it stops mattering can reach you without waiting for the "
            "next such notification. One that named no such moment stays held however "
            "long you wait: no reach setting makes it urgent.[/]"
        )
    elif asked.reach is NotificationReach.OFF:
        console.print(
            "\n[dim]Anything of that class I am already holding is now due to be ruled "
            "out too, on my next sweep rather than this instant; it stays readable in "
            "'assistant notifications' either way. Nothing already sent is recalled.[/]"
        )


def _tuned(current: NotificationPreferences, asked: _Tuning) -> NotificationPreferences:
    """The settings to write: ``current`` with the named axes replaced (ADR-0130 §6).

    Pure, so the substitution can be checked without a hub. A named class replaces
    that class's row and leaves every other row alone — which is what keeps
    ``NotificationPreferences``' refusal of two rows for one class unreachable from
    here rather than merely unlikely. A row is written even where the reach equals the
    shipped default, because "I have decided this class holds" and "I have not decided
    about this class" are the same setting today and only one of them is something the
    user did.

    **The budget window is relayed and never set**, and that is not an omission: the
    setting ADR-0130 §6 makes tunable is the count, expressed per rolling window,
    whose figure the ADR fixes at twenty-four hours. ``notification-settings`` renders
    the window so the count is readable, and #982 holds the question of whether a user
    should be able to move it.

    Constructed rather than copied: :meth:`~pydantic.BaseModel.model_copy` skips
    validation, and this value's validator is the one refusing a duplicated class.

    Args:
        current: The settings in force, as the store handed them back.
        asked: What the user named, parsed.

    Returns:
        The value to send.

    Raises:
        ValueError: If the result is not a coherent settings value.
    """
    reaches = current.reaches
    if asked.notification_class is not None and asked.reach is not None:
        kept = tuple(row for row in reaches if row.notification_class != asked.notification_class)
        reaches = (
            *kept,
            ClassReach(notification_class=asked.notification_class, reach=asked.reach),
        )
    if asked.clear_quiet_windows:
        windows: tuple[QuietWindow, ...] = ()
    elif asked.quiet_windows:
        windows = asked.quiet_windows
    else:
        windows = current.quiet_windows
    return NotificationPreferences(
        reaches=reaches,
        quiet_windows=windows,
        interruption_budget=(current.interruption_budget if asked.budget is None else asked.budget),
        budget_window=current.budget_window,
    )


# --- rendering (ADR-0042 §4, §6: escaping is the adapter's, per target) --


def _safe(value: str, *, keep_line_breaks: bool = False) -> str:
    r"""Neutralise tool-supplied data for this terminal (ADR-0042 §4).

    "Safe" is target-specific, so the engine carries values verbatim and each
    adapter escapes for its own output. Here that means two things: replace
    non-printable control characters (an ANSI escape like ``\\x1b[2J`` a terminal
    would act on) with the replacement character, and escape Rich markup so a
    value like ``[red]`` is shown, not interpreted.

    **``\n`` is a replaced character by default, and that is not incidental**
    (#1336). Almost every surface here interpolates a value into a line the CLI
    itself authored — ``  [dim]Why:[/] {reason}``, ``  {index}. {intent}``, a
    ``[bold cyan]{id}[/]`` under a heading — so a value carrying a newline does not
    merely wrap: it forges a *second* line indistinguishable from one this adapter
    wrote. That is §4's threat exactly, arriving without a single control character,
    and eating the newline is what stops it. Every caller but :func:`_safe_prose`
    takes this default.

    Args:
        value: The value as the engine carries it, verbatim.
        keep_line_breaks: Whether ``\n`` survives instead of being replaced. Only
            for a value rendered as a block of its own, where there is no
            adapter-authored text on the line for a forged break to imitate; pass it
            through :func:`_safe_prose`, which also settles ``\r``.

    Returns:
        The text to write to this terminal.
    """
    kept = "\t \n" if keep_line_breaks else "\t "
    cleaned = "".join(ch if ch.isprintable() or ch in kept else "�" for ch in value)
    return escape(cleaned)


def _safe_prose(value: str) -> str:
    r"""Neutralise engine-supplied text that is *legitimately* multi-line (#1336).

    **The same neutralisation, minus the one replacement prose cannot afford.** A
    composed answer (ADR-0170 §8) is the first engine-supplied value whose newlines
    are content rather than smuggling: it is printed as a block of its own, with no
    label sharing its line, so a break in it forges nothing — the argument
    :func:`_safe` records for taking the opposite default everywhere else. Before
    the carve-out, every paragraph break in a live answer rendered ``��``. Rich
    markup is still escaped and every other non-printable character is still
    replaced, because those are what a terminal would *act on* and a newline is not.

    **``\r`` is normalised, not kept and not replaced**, and the two failures it sits
    between are why. A carriage return *is* a character a terminal acts on — it
    returns the cursor to column 0, so text after it overwrites text before it,
    which is §4's threat in its purest form and must not reach the screen. But
    replacing it leaves ``deep work.�\nOne caveat`` for a model that simply emits
    CRLF: the bug half-fixed. Rewriting ``\r\n`` and a lone ``\r`` to ``\n`` settles
    both at once — it removes the character that overwrites and yields the break the
    producer meant, and a ``\n`` can only ever *add* a line, never hide one.

    **Escaping happens over the whole value, never line by line.** Neutralising each
    line and joining with ``\n`` looks equivalent and is not: Rich's tag pattern
    matches across a newline, so ``[red\nbold]`` survives per-line escaping intact
    and Rich then consumes it as markup — a value that reaches the screen *emptied*
    of what it said. So the line endings are settled first and :func:`_safe` is asked
    once, of the whole.

    Args:
        value: The prose as the engine carries it, verbatim.

    Returns:
        The text to write to this terminal, its line structure intact.
    """
    return _safe(value.replace("\r\n", "\n").replace("\r", "\n"), keep_line_breaks=True)


#: What may follow a ``[`` in Rich markup, taken from the character class its
#: escaper and its parser share (``\[[a-z#/@][^[]*?]``). A ``[`` followed by
#: anything else is text under both, so :func:`_settled_prefix` need not hold it.
_TAG_START: Final = frozenset("abcdefghijklmnopqrstuvwxyz#/@")


def _settled_prefix(text: str) -> str:
    r"""The longest prefix of ``text`` whose neutralisation later text cannot change.

    **The renderer's own boundary, which is what ADR-0173 §10's second clause asks
    for.** A streamed answer is neutralised "to text the adapter has *accumulated*,
    never independently to each chunk as it arrives", and "an adapter that renders
    progressively neutralises on boundaries its own renderer controls". This is that
    boundary: everything before the cut neutralises to a fixed string no matter what
    arrives next, so writing it out early can never be revised, and everything from
    the cut is held until it settles. The hub chooses where the *chunks* break; it
    never chooses where the *escaping* is decided.

    Three things at the tail are unsettled, and each is a way :func:`_safe_prose`
    would read the same characters differently once more text follows them:

    - **An unclosed ``[`` that could still open a tag.** Rich escapes a *complete*
      tag — its pattern is ``\[[a-z#/@][^[]*?]`` — so ``[/dim`` alone is left
      verbatim and becomes ``\[/dim]`` the moment a ``]`` lands. Splitting there is
      exactly the evasion §10 names, so the cut falls at the last ``[`` with no ``]``
      after it. Only the *last* one can matter: the body admits no ``[``, so an
      earlier one can never reach a ``]`` across a later one. And only one whose next
      character is a tag start (or is not there yet) is held — ``[1`` and ``[Options``
      can never become markup under either Rich's escaper or its parser, and holding
      those would stall the rest of an ordinary answer behind a bracket, which is the
      streaming this whole path exists to do. A ``[`` that already has a ``]`` after
      it is settled: the match is lazy and ends at that ``]``.
    - **A trailing run of ``\``.** Rich's escape doubles the backslashes running
      into a tag and appends one to a value ending in an odd number of them, so a
      run at the tail is rewritten by whatever follows it.
    - **A trailing ``\r``.** :func:`_safe_prose` folds ``\r\n`` to one ``\n`` and a
      lone ``\r`` to ``\n``; which of the two a final ``\r`` is depends on the next
      character.

    Args:
        text: The answer as accumulated so far, verbatim and un-neutralised.

    Returns:
        The prefix safe to neutralise and write now. Possibly empty — a stream whose
        first chunk is ``[dim`` settles nothing until its ``]`` arrives.
    """
    cut = len(text)
    opening = text.rfind("[")
    unclosed = opening != -1 and "]" not in text[opening:]
    if unclosed and (opening + 1 == len(text) or text[opening + 1] in _TAG_START):
        cut = opening
    elif text.endswith("\r"):
        cut -= 1
    while cut > 0 and text[cut - 1] == "\\":
        cut -= 1
    return text[:cut]


@final
class _StreamedReply:
    """One streamed answer, accumulated and written out as it settles (ADR-0173 §10).

    **It holds the raw text, not the rendered text**, which is the whole of §10's
    second clause. :func:`_safe_prose` is asked of the accumulation and never of a
    chunk, so the escaping is decided over text this class holds rather than at a
    boundary the producer picked; :func:`_settled_prefix` then says how much of that
    accumulation can be written without the answer being revised later.

    **Nothing is written that the terminal outcome does not confirm.** ADR-0173 §3
    makes :attr:`TurnOutcome.reply` the answer and the chunks "a rendering of it in
    flight", so :meth:`settle` writes the tail only where the authoritative reply
    extends what is already on screen, and says so plainly where it does not. The
    held-back remainder is deliberately not flushed on its own: it reaches the screen
    from the outcome's ``reply``, or not at all.
    """

    def __init__(self) -> None:
        """Start empty, having written nothing."""
        self._accumulated = ""
        self._settled = ""
        self._written = ""
        self._line_open = False

    @property
    def shown(self) -> str:
        """The raw text already written to the terminal."""
        return self._settled

    def take(self, chunk: ReplyChunk) -> None:
        """Accumulate one chunk and write however much of the answer it settles.

        Args:
            chunk: The instalment just yielded.
        """
        self._accumulated += chunk.text
        self._write_through(_settled_prefix(self._accumulated))

    def settle(self, reply: str | None) -> None:
        """Finish the answer against the value ADR-0173 §3 makes authoritative.

        Args:
            reply: The terminal outcome's ``reply``. ``None`` where the turn owed no
                answer or published none.
        """
        if reply is not None and reply.startswith(self._settled):
            # The ordinary case, and the one a turn that streamed nothing takes too:
            # every prefix extends the empty string, so this writes the whole reply.
            self._write_through(reply)
            self._end_line()
            return
        self._end_line()
        if not self._settled:
            return
        # ADR-0173 §3: "no implementation treats an accumulated chunk sequence as the
        # record of what the assistant said". The prose above is already on screen and
        # cannot be recalled, so it is disowned in words and the answer stated after it.
        console.print(
            "[yellow]Note:[/] the hub did not confirm the text above as this turn's "
            "answer, so read what follows instead of it."
        )
        if reply is not None:
            console.print(_safe_prose(reply))

    def abandon(self) -> None:
        """Give up on a stream that will produce no outcome, leaving the line whole.

        A partly written answer has no trailing newline — it was written with none, so
        the next chunk could continue the line — so an error rendered after it would
        otherwise begin on the same line as the prose it is about.
        """
        self._end_line()

    def _write_through(self, settled: str) -> None:
        """Write the part of ``settled`` not already on screen.

        ``settled`` extends what was written, so its neutralisation extends what was
        neutralised, and the difference is what has not been seen yet.

        Args:
            settled: A raw prefix of the answer that is safe to neutralise now.
        """
        if len(settled) <= len(self._settled):
            return
        rendered = _safe_prose(settled)
        console.print(rendered[len(self._written) :], end="", soft_wrap=True, highlight=False)
        self._settled = settled
        self._written = rendered
        self._line_open = not rendered.endswith("\n")

    def _end_line(self) -> None:
        """Close the line the answer was written on, if one is open. Idempotent.

        **Written without a line ending and closed once** — the parts arrive
        mid-sentence, and Rich would otherwise break the answer wherever a chunk
        happened to end. ``soft_wrap`` is for the same reason: wrapping each instalment
        to the console width independently would hard-wrap an answer at whatever column
        each chunk stopped at, and the terminal wraps the whole far better. Anything
        printed after the answer therefore has to be given its own line first.
        """
        if self._line_open:
            console.print()
            self._line_open = False


def _argument(value: str) -> str:
    """One value, rendered as a shell argument a person can paste (#984).

    **Two escapings in one fixed order, and neither substitutes for the other.**
    :func:`shlex.quote` answers "where does this argument end", which is the shell's
    question and is asked of the *real* value; :func:`_safe` answers "what may this
    terminal be handed", which is Rich's question and is asked of whatever will be
    written. So the value is quoted first and the quoted form is what gets escaped —
    the other order would hand the shell the escape characters ``_safe`` inserted and
    quote those instead.

    Without this, a value carrying an interior space renders a line that is a *valid*
    command against the wrong argument when pasted: ``assistant revoke my calendar``
    revokes ``my``. Neither ``Identifier`` nor ``NonBlankEncodableText`` forbids that
    space, and ADR-0102 §2 keeps a declared source name byte-exact precisely so it is
    compared unnormalised — so the admissible value is the one that breaks.

    **It is a necessary condition and not a sufficient one.** Quoting settles where the
    argument ends; it cannot settle whether the argument survives being *displayed*.
    Every caller therefore asks :func:`_is_pasteable` first and prints
    :func:`_uncopyable` where the answer is no — see there for the failure that catches.

    Args:
        value: The argument as the engine carries it, verbatim.

    Returns:
        The text to interpolate into a printed command.
    """
    return _safe(shlex.quote(value))


def _uncopyable(
    subject: str, remedy: str = "The command still takes it, given the exact bytes."
) -> str:
    r"""The line that replaces a command hint whose argument cannot be shown (#1013).

    **A wrong command is worse than no command, and quoting does not prevent one.**
    :func:`_argument` answers the shell's question and :func:`_safe` the terminal's, and
    neither answers this one: ``_safe`` *replaces* a character a terminal must not be
    handed, so a value carrying one renders — inside perfectly correct shell quotes — as
    a command naming something that does not exist. That is the failure quoting was
    added to prevent, arriving one step later and looking like a working instruction.

    Reachable rather than theoretical. ``Identifier`` and ``NonBlankEncodableText``
    require encodability and nothing more, and ADR-0102 §4 admits a declared source name
    that equals its own ``strip()`` — so ``"my\ncalendar"`` is an admissible reader
    identity and ``"q\x1b[2J1"`` an admissible question id.

    The absence is explained rather than left as a gap the reader has to notice, and the
    act is never withdrawn: what is withheld is the *copyable* line, and the command
    itself still takes the value from anything that can carry the exact bytes.

    Args:
        subject: What cannot be shown, opening the sentence, e.g. ``"Its id"``.
        remedy: How to perform the act anyway, closing it.

    Returns:
        The text to print in the hint's place.
    """
    return (
        f"[yellow]{subject} holds characters this terminal cannot show[/], so there is "
        "no command here to copy — one written from what is on screen would name "
        f"something else. {remedy}"
    )


def _print_hint(line: str) -> None:
    """Print a line offering a command to copy, without folding the command (#1023).

    **Rich wraps by inserting a real newline**, not by leaving the terminal to fold
    the line, so a hint wider than the console arrives on screen as two lines and
    pastes as *two commands*: ``assistant dismiss`` with no argument, and then the
    argument as a command of its own. Where the argument is quoted the fold lands
    inside the quotes instead, and the command then names a value with a newline in
    it. Neither is exotic — no field a hint carries has a length limit, so the
    trigger is a long value plus a narrow terminal.

    ``soft_wrap`` is the same answer :class:`_StreamedReply` reaches for one screen
    over and for the same reason: Rich emits the line as it stands and the terminal
    folds it, which costs a word break mid-word and keeps the line *one* line to
    anything that copies it. It is the whole of the decision, taken once here rather
    than per site — an ``overflow`` or ``crop`` setting would instead **truncate** a
    long hint, which turns a command that pastes wrongly into one that pastes
    silently short.

    **It is for the print that carries the command, and only that one.** A hint
    embedded in a paragraph takes this too, because the fold hazard is the same
    wherever the command sits; prose with no command in it keeps Rich's wrapping,
    which reads better and has nothing to lose.

    Args:
        line: The hint, with its markup, exactly as it would have been printed.
    """
    console.print(line, soft_wrap=True)


def _render_turn(outcome: TurnOutcome, *, streamed: _StreamedReply | None = None) -> bool:
    """Render one turn's answer, its plan, its degraded notices, and its step outcome.

    ``streamed`` is the answer already on screen when the turn was driven through
    ``converse_streaming``; the reply is finished against it rather than printed
    afresh (ADR-0173 §10). It is ``None`` for a one-result call — a ``resume``, or a
    caller that chose ``converse`` — and then the reply is printed whole as before.
    Either way **the step account is rendered whether or not chunks were rendered**,
    which is §10's third clause and is the same obligation ADR-0170 §6 already
    carried.

    **A routed pass renders its routed account and nothing else** (ADR-0197 §10). It
    drove no plan and no step — §1 ends the pipeline at a taken route and §8 makes
    ``routed`` and ``step`` mutually exclusive — so the plan and step blocks below
    are not merely empty for it, they describe a pass that did not happen. The
    account is rendered *after* the reply and in addition to it, never instead of it:
    where the two disagree the account is correct by construction, and no flag here
    resolves that disagreement in the reply's favour.

    ``outcome.turn`` is ``None`` on a resume driven from a **recovered** park
    (ADR-0052 §3) — a confirmation reconstructed from durable state after a restart
    has no live turn to render — so only the step is shown there. The action itself
    was already shown from the recovered confirmation before the user answered.

    **The answer is rendered in addition to the step account, never instead of it**
    (ADR-0170 §6). ADR-0084 §8's rule binds unchanged: the disposition line, the
    named step's status and failure, and the exit code #531 fixed are all still
    printed, and none of them is dropped on the ground that a reply is now present.
    That is the whole enforceable half of ADR-0170, and it is enforceable precisely
    because it does not depend on the model — a completion that claims it sent the
    email is contradicted on the same screen by a line saying no tool was available,
    on every turn, whether or not the prompt worked. Where the two disagree the step
    account is correct by construction, and nothing here resolves that disagreement
    in the reply's favour.

    Returns:
        Whether this turn's deterministic account says the system failed to do what
        was asked, which the caller folds into the process exit code (#531). On a
        routed pass that is :func:`_render_routed`'s answer.
    """
    turn = outcome.turn
    if outcome.capture_degraded:
        # ADR-0074 §9 item 6: capture failure degrades the turn rather than failing
        # it — the answer is still the answer — but a user whose turns are silently
        # not being recorded would not find out until they tried to continue.
        console.print(
            "[yellow]Note:[/] this turn was not recorded, so it will not be part of "
            "this conversation's history."
        )
    if turn is not None and turn.memory_degraded:
        console.print(
            "[yellow]Note:[/] personal memory was unavailable, so this answer is generic."
        )
    _render_reply(outcome, streamed=streamed)
    routed = outcome.routed
    if routed is not None:
        # ADR-0197 §8: `routed` and `step` are never both present, and a routed pass
        # carries no turn — so there is no plan below and no step account, and the
        # routed account is the whole of what this turn deterministically did.
        return _render_routed(routed)
    if turn is not None:
        plan = turn.plan
        if plan.rationale:
            console.print(f"[bold]Plan:[/] {_safe(plan.rationale)}")
        if not plan.steps:
            console.print("[dim]No action was needed.[/]")
        for index, planned in enumerate(plan.steps, start=1):
            console.print(
                f"  {index}. {_safe(planned.intent)} [dim]({_safe(planned.capability)})[/]"
            )

    step = outcome.step
    if step is None or step.confirmation is not None:
        return False
    return _render_step(step)


def _render_reply(outcome: TurnOutcome, *, streamed: _StreamedReply | None = None) -> None:
    """Print the composed answer, and say where composing it did not finish.

    Four shapes, read off two values (ADR-0170 §4 as ADR-0173 §6 widened it): no
    answer was owed, one was owed and none was produced, one was owed and **part** of
    it was, one was owed and the whole of it was.

    **Neutralised before display** (ADR-0170 §8). A composed answer is
    engine-supplied text — model output, in the assistant's own voice — so it is put
    through the same neutralisation as the confirmation content, the plan's
    rationale and a policy's reason (ADR-0042 §4). Rich markup in a reply is
    otherwise a control sequence this terminal interprets.

    **Through :func:`_safe_prose`, because a reply is the first such value that is
    legitimately multi-line** (#1336). §8's obligation is discharged unchanged —
    Rich markup escaped, every character a terminal would act on replaced — but a
    reply is printed as a block of its own rather than interpolated into a line this
    adapter wrote, so its paragraph breaks forge nothing and are content. Rendering
    them ``��``, as the shared one-line helper did, damaged every multi-paragraph
    answer the assistant gave.

    **A degraded turn is rendered as a statement, never as silence** (ADR-0170 §6).
    A turn that sent an email and could not then describe it still tells the user the
    email was sent, in the same words it would have used before ADR-0170 existed; the
    only thing missing is the prose that was going to sit above them. Rendering it
    silently would leave a user unable to tell "no answer was owed" from "an answer
    was owed and could not be composed" — the distinction ``reply_degraded`` exists
    to carry — and rendering it as a *failure of the step* would say the action did
    not happen when the account says it did.

    **An answer that began and did not finish is shown, and said to be incomplete**
    (ADR-0173 §§6, 10). That fourth shape — a ``reply`` set *beside*
    ``reply_degraded`` — is reachable only from a stream, where a failure or the
    payload ceiling stopped a composition whose first words the user has already
    read. §10 obliges "the account it carries plus a statement that the answer is
    incomplete", and discarding the prose instead would make the authoritative value
    contradict what is on their screen (ADR-0173 §6). The statement comes *after* the
    text for the same reason it is a statement at all: it is about prose the user has
    by then read.

    A ``None`` reply with ``reply_degraded`` unset is a shape that owed no answer at
    all: a parked confirmation, whose question the caller renders instead, or a
    resume driven from a recovered park (ADR-0170 §4). Neither prints anything here.

    Args:
        outcome: The turn's terminal outcome.
        streamed: The answer already written by ``converse_streaming``'s chunks, or
            ``None`` where the turn was driven as one result.
    """
    if streamed is not None:
        streamed.settle(outcome.reply)
    elif outcome.reply is not None:
        console.print(_safe_prose(outcome.reply))
    if not outcome.reply_degraded:
        return
    if outcome.reply is None:
        console.print(
            "[yellow]Note:[/] no answer could be composed for this turn, so what "
            "follows is the record of what was done and nothing more."
        )
        return
    console.print(
        "[yellow]Note:[/] that answer is incomplete — composing it did not finish, so "
        "it stops where it stops; what follows is the record of what was done."
    )


def _render_step(step: StepOutcome) -> bool:
    """Render what became of the step this pass drove — gate *and* outcome (#531).

    **The disposition is the gate's verdict; the named step's ``status`` and
    ``failure`` are the outcome** (ADR-0084 §8, ADR-0085 §7). This adapter is where
    #531's defect lived: it read ``disposition`` and discarded ``state``, so a tool
    that raised — recorded in ``plans.db`` as ``status: "failed"`` with its
    ``kind``, exactly as ADR-0029 §4 requires — was rendered "Done." and exited
    ``0``. A scripted caller "cannot tell a successful turn from a failed one
    without opening ``plans.db``".

    **Only ``SUCCEEDED`` is success, and taking the rule that way round is the
    load-bearing half.** ``FAILED`` is the obvious non-success and
    ``INDETERMINATE`` is the other one: ``core/types.py``'s ``_FAILURE_STATUSES``
    holds both, "because both are finished, non-successful outcomes", and both
    *require* a ``failure`` on the record. A renderer written as "not ``FAILED``
    means done" reproduces #531 exactly one status over — and on the status
    ADR-0014 §4 makes durable *because* it must be resolved explicitly, which is the
    one a user most needs to be told about.

    :attr:`~ai_assistant.core.types.StepOutcome.step_id` is what makes the outcome
    *addressable*: ``state.steps`` is the whole tuple and ``tool_id`` cannot
    identify a step, since two steps may bind the same tool.

    Args:
        step: What the pass did with the plan's step.

    Returns:
        Whether the step did **not** succeed, which the caller folds into the
        process exit code.
    """
    if step.disposition is not Disposition.EXECUTED:
        _render_disposition(step.disposition, step.tool_id)
        return False

    named = [one for one in step.state.steps if one.step_id == step.step_id]
    if not named:
        # Unreachable by contract — ``step_id`` addresses exactly one execution
        # record, and the conformance suite holds every implementation to it. If it
        # ever is reached, "we cannot tell" must not render as success: that is the
        # whole of what #531 reported, and a green exit code for an unknown outcome
        # is the version of it a script would trust.
        console.print(
            "[yellow]The step's own execution record could not be found, so whether it "
            "succeeded cannot be shown.[/]"
        )
        return True

    execution = named[0]
    if execution.status is StepStatus.SUCCEEDED:
        _render_disposition(step.disposition, step.tool_id)
        return False

    tool = _safe(step.tool_id) if step.tool_id is not None else "the selected tool"
    failure = execution.failure
    # ``failure`` is required on both non-successful finished statuses
    # (``core/types.py``'s ``_FAILURE_STATUSES``), so the ``None`` arm is the type's
    # optionality rather than a state this can reach.
    cause = "" if failure is None else f" {_safe(failure.message)}"
    kind = "" if failure is None or failure.kind is None else f" [dim]({failure.kind.value})[/]"
    console.print(f"{_step_headline(execution.status, tool)}{cause}{kind}")
    return True


def _step_headline(status: StepStatus, tool: str) -> str:
    """Say what became of a step that did not succeed, in its own terms.

    ``FAILED`` and ``INDETERMINATE`` are both non-successful and they are not the
    same news: a failure is a call that finished badly, while an indeterminate step
    "awaits explicit resolution" (``TERMINAL_STEP_STATUSES``) — the tool may have
    acted. Collapsing them into one word would tell a user the side effect did not
    happen when nobody knows whether it did.
    """
    if status is StepStatus.FAILED:
        return f"[red]Failed.[/] {tool} ran and did not succeed."
    if status is StepStatus.INDETERMINATE:
        return (
            f"[red]Unresolved.[/] {tool} was called and the outcome could not be "
            f"determined, so it may or may not have taken effect."
        )
    # Anything else that is not `SUCCEEDED` after an `EXECUTED` disposition: still
    # not success, and said as plainly as the status allows.
    return f"[yellow]Not finished.[/] {tool} is {_safe(status.value)}."


# --- the routed account (ADR-0197 §10) --------------------------------------
#
# **Rendered beside the reply, never instead of it, and never suppressed.** ADR-0197
# §10 binds here for ADR-0170 §6's reason and sharpens it: on a routed pass the
# composing stage saw two enum values and nothing else (§6), so the worst prose it
# can produce is prose about the wrong thing, while the account beside it is typed
# data from the store that no prompt influenced. Where the two disagree the account
# is correct by construction, and nothing here — no setting, no flag — resolves that
# disagreement in the reply's favour.
#
# **Every word around the values is this adapter's own, selected by the enum
# member** (§7's card clause, read across the whole account). No free text the
# router produced reaches the screen: the operation and the outcome are closed
# vocabularies, and the listing is records the store already held. Each is put
# through :func:`_safe` on the way out (§10's last clause) — a stored `source` is
# whatever a reader declared it to be, and a belief's content is the user's own
# words, neither of which this terminal may be handed unescaped.


#: What the ask was routed to, in words, for the one line that says what was asked
#: for. Total over :class:`RoutableOperation` so a member added under ADR-0197 §3's
#: widening rule fails here rather than rendering as its enum value.
#:
#: **ADR-0217 §7's two acts are entries here and not a rendering decision** (§11). That
#: section's closing clause admits "no gateway route, no rendering and no further
#: consumer", and this map is neither: the widening lane owes it, by the sentence above
#: and by ADR-0197 §3's widening rule, and deferring it is the failure that sentence
#: names — `_render_routed_candidates`' fall-through raises for any confirm-owed member
#: with no arm, which both acts are. What §11 forbids a lane to add is a rendering of a
#: **placement** — a reach, a setter, an instant — and nothing here renders one. The
#: entries are ADR-0137 §1 adaptation into a map this adapter already owns, not the
#: §4 consumer that is briefed after a merged contract: neither act is called here.
_ROUTED_ASKED: Final[Mapping[RoutableOperation, str]] = {
    RoutableOperation.QUESTIONS: "list what is waiting on your answer",
    RoutableOperation.RECENT_READS: "list the attempts to read your sources",
    RoutableOperation.RECENT_INVOCATIONS: "list what I did on an authorisation",
    RoutableOperation.RECENT_DECISIONS: "list what the permission layer ruled",
    RoutableOperation.STANDING_GRANTS: "list the sources you allow me to read",
    RoutableOperation.SPEND_TOTALS: "report what the world has cost",
    RoutableOperation.FORGET: "forget one belief",
    RoutableOperation.REVOKE: "withdraw the grant on one source",
    RoutableOperation.FORGET_QUESTION: "forget one deferred question",
    RoutableOperation.GUARD: "keep one belief for you alone",
    RoutableOperation.UNGUARD: "let one belief be spoken to anyone again",
}

#: What did **not** happen, for every ending that performed nothing. Total for the
#: same reason, and phrased per operation because "nothing was done" is the sentence
#: a user cannot act on: what they need to know is that the belief is still held.
_ROUTED_UNDONE: Final[Mapping[RoutableOperation, str]] = {
    RoutableOperation.QUESTIONS: "nothing was listed",
    RoutableOperation.RECENT_READS: "nothing was listed",
    RoutableOperation.RECENT_INVOCATIONS: "nothing was listed",
    RoutableOperation.RECENT_DECISIONS: "nothing was listed",
    RoutableOperation.STANDING_GRANTS: "nothing was listed",
    RoutableOperation.SPEND_TOTALS: "no total was reported",
    RoutableOperation.FORGET: "the belief is still held",
    RoutableOperation.REVOKE: "the grant still stands",
    RoutableOperation.FORGET_QUESTION: "the question is still there",
    RoutableOperation.GUARD: "the belief is placed as it was",
    RoutableOperation.UNGUARD: "the belief is placed as it was",
}

#: What a confirm-owed operation did, once it has run. Total over the members
#: ADR-0197 §3 tags confirm-owed, and reached only from :attr:`RouteOutcome.PERFORMED`
#: — a read-only ``PERFORMED`` renders its listing instead, and has one to render.
#:
#: **``unguard``'s sentence is hedged and the other four are not**, which is ADR-0217
#: §7 rather than caution: an ``unguard`` whose record carries a ``DERIVED`` placement
#: writes nothing and returns that placement unchanged, and a routed pass has no way to
#: tell the two apart — ``perform`` drops the returned value, because §6 keeps every
#: operation's result out of the composed reply. Claiming the belief is now speakable
#: would therefore be a claim this surface cannot check, on the one axis where the
#: meaning lost is the restrictive one. ``guard`` needs no hedge: every branch of §3
#: leaves the record at reach ``OWNER``, the refusal included.
_ROUTED_DONE: Final[Mapping[RoutableOperation, str]] = {
    RoutableOperation.FORGET: "That belief is destroyed.",
    RoutableOperation.REVOKE: "That grant is withdrawn — I may no longer read that source.",
    RoutableOperation.FORGET_QUESTION: "That question is destroyed.",
    RoutableOperation.GUARD: "That belief is kept for you alone.",
    RoutableOperation.UNGUARD: (
        "I acted on that belief. A narrowing I derived myself still stands — an act "
        "does not lift one."
    ),
}

#: What ADR-0217 §7's two acts carry on their confirmation card, beside the belief.
#: Keyed on the member for :data:`_ROUTED_ASKED`'s reason — every word around the
#: subject is this adapter's own and none of it is the router's — and holding exactly
#: the two acts, which is also what :func:`_render_operation_confirmation` tests
#: membership of to pick its branch.
#:
#: Each says what the act does **and** what it does not, because the second half is
#: what a person cannot see from the belief on screen: guarding destroys nothing, and
#: unguarding does not lift a narrowing this system derived (ADR-0204 §5, ADR-0217 §3).
_PLACEMENT_ACT_NOTE: Final[Mapping[RoutableOperation, str]] = {
    RoutableOperation.GUARD: (
        "\n  This keeps the belief for you alone: I will not put it, or a reply that "
        "rests on it, on a channel anyone else can hear. It destroys nothing, changes "
        "nothing I hold, and you can undo it."
    ),
    RoutableOperation.UNGUARD: (
        "\n  This lets the belief be spoken to anyone again. Where I narrowed it "
        "myself, that narrowing stands — an act does not lift one — and nothing here "
        "makes a private detail speakable that was never yours to share."
    ),
}

#: The two endings on which this system failed to do what was asked, which is what
#: the process exit code carries (#531's rule, read one surface over). Everything
#: else — a refusal, an ambiguity, a lookup that matched nothing — is an **answer**
#: to the request rather than a failure of it, exactly as a non-``EXECUTED``
#: disposition is, and exits ``0``.
_ROUTED_FAILURES: Final[frozenset[RouteOutcome]] = frozenset(
    {RouteOutcome.UNRECORDED, RouteOutcome.FAILED}
)


def _routed_records[T](
    operation: RoutableOperation, listing: RoutedListing, arm: type[T]
) -> tuple[T, ...]:
    """Read a routed listing as the arm ``operation`` names (ADR-0197 §8).

    **The discriminator is the operation and never the value's shape**, which is §8
    in terms: "an empty tuple is a legal value of every arm, so the shape decides
    nothing on exactly the case a listing is most likely to take". So the caller
    names the arm it is about to render, this checks that against
    :func:`~ai_assistant.core.types.routed_listing_arm` — ``core``'s own mapping,
    not a second copy of it here — and the cast states to the type checker what the
    check established.

    Args:
        operation: The routed operation, which is the discriminator.
        listing: The listing carried beside it.
        arm: The element type the caller is about to render.

    Returns:
        The same tuple, typed as the arm.

    Raises:
        AssertionError: If ``operation`` names a different arm, which is unreachable
            through :class:`~ai_assistant.core.types.RoutedOperation`'s own validator
            and is therefore a defect in this dispatch rather than a state.
    """
    if routed_listing_arm(operation) is not arm:  # pragma: no cover - see below
        # Unreachable through `RoutedOperation`'s own validator, which holds every
        # element of a listing to the arm `operation` names. Raised rather than
        # silently rendered, because the alternative is a renderer reading one
        # record type's fields off another's.
        raise AssertionError(f"{operation.value} does not list {arm.__name__}")
    return cast("tuple[T, ...]", listing)


def _render_routed(routed: RoutedOperation) -> bool:
    """Render what one routed pass did — operation, outcome, and any listing (§10).

    **A park renders as the question and nothing else.** ADR-0197 §10's third clause
    keeps the composing stage out of a routed park entirely, "for its own reason: the
    confirmation is what the user must answer, and prose beside it competes with the
    question" — so the card is the whole of the account here, exactly as
    :func:`_render_turn` renders no step account for a parked step.

    **The card is rendered here rather than by the approver**, which is what makes
    ``--yes`` safe: :func:`_drive_turn` calls this before it collects the answer, so
    a non-interactive approval cannot destroy something the user was never shown
    (ADR-0073 §5, ADR-0052 §4, and ADR-0197 §7's last clause naming §5 by hand).

    Returns:
        Whether this system failed to do what was asked, which the caller folds into
        the process exit code. ``UNRECORDED`` and ``FAILED`` are that failure and
        nothing else is: a refusal is the user's own ruling, and an ambiguity or a
        lookup that matched nothing is an answer to the request.
    """
    card = routed.confirmation
    if card is not None:
        _render_operation_confirmation(card)
        return False
    console.print(_routed_headline(routed))
    listing = routed.listing
    if listing is not None:
        _render_routed_listing(routed.operation, routed.outcome, listing)
    return routed.outcome in _ROUTED_FAILURES


def _routed_headline(routed: RoutedOperation) -> str:  # noqa: PLR0911 — one return per RouteOutcome, and the enumeration is the point
    """Say what became of the routed operation, in this adapter's own words.

    Total over :class:`RouteOutcome`, so a ninth member fails
    :func:`~typing.assert_never` here rather than rendering as its enum value.

    **``UNRECORDED`` and ``FAILED`` say opposite things and are worded to** (ADR-0197
    §8, and §12's discrimination clause, which requires a surface that renders the
    two alike to fail a test). ``UNRECORDED`` means the operation was never called
    and nothing was destroyed; ``FAILED`` means it was called and raised, and whether
    it took effect is not asserted. Rendering them alike would tell a user their
    belief might be gone when this decision guarantees it is not.

    **``UNRECORDED`` says to ask again and never to try the token again** (§7). The
    park is already claimed by the time that ending is reached, so a surface offering
    a retry would be offering a token that now raises ``UnknownContinuationError``.

    **``REFUSED`` is a ruling and not an error** (§7). No ``ActionPolicy`` was
    consulted and no ``PermissionDecision`` recorded, so there is nothing here for a
    refusal to be *except* the answer the user gave, and it is worded as one.
    """
    asked = _ROUTED_ASKED[routed.operation]
    undone = _ROUTED_UNDONE[routed.operation]
    match routed.outcome:
        case RouteOutcome.PERFORMED:
            if routed.operation.confirm_owed:
                return f"\n[green]Done.[/] {_ROUTED_DONE[routed.operation]}"
            return f"\n[bold]I read my own record for that[/] — you asked me to {asked}."
        case RouteOutcome.AWAITING_CONFIRMATION:  # pragma: no cover - the card is rendered above
            return f"\n[bold yellow]Waiting on your answer[/] before I {asked}."
        case RouteOutcome.REFUSED:
            return f"\n[yellow]Not done.[/] You said no, so {undone}."
        case RouteOutcome.AMBIGUOUS:
            return (
                f"\n[yellow]More than one thing matches that.[/] I will not guess "
                f"which you meant, so {undone}. Here is everything that matched — "
                f"say which one, or use the command for it directly."
            )
        case RouteOutcome.AMBIGUOUS_TRUNCATED:
            return (
                f"\n[yellow]More than one thing matches that, and more than I can "
                f"show.[/] I will not guess which you meant, so {undone}. Here are "
                f"the matches I can show — narrow it down, or use the command for it "
                f"directly."
            )
        case RouteOutcome.NOT_FOUND:
            return f"\n[yellow]Nothing matches that.[/] I found nothing to act on, so {undone}."
        case RouteOutcome.UNRECORDED:
            return (
                f"\n[red]Not attempted.[/] I could not write the record that has to "
                f"exist before I act, so I did not act: {undone}. Nothing is waiting "
                f"on you and there is nothing to retry — ask me again."
            )
        case RouteOutcome.FAILED:
            return (
                f"\n[red]Failed.[/] I tried to {asked} and it raised. Whether it took "
                f"effect is not something I can tell you."
            )
        case _:  # pragma: no cover - exhaustive
            assert_never(routed.outcome)


def _render_routed_listing(
    operation: RoutableOperation, outcome: RouteOutcome, listing: RoutedListing
) -> None:
    """Render a routed listing with the renderer this adapter already has for it.

    ADR-0197 §12's last Normative is why there is no new renderer here: "each renders
    the routed account beside the reply with the renderer it already has for the
    operation". Every arm of :data:`~ai_assistant.core.types.RoutedListing` is a type
    ``assistant questions``, ``reads``, ``invocations``, ``decisions``, ``granted``,
    ``spend`` and ``beliefs`` already render, so a routed answer and the same
    operation's typed-door answer read alike — which is ADR-0197 §2's third clause
    surviving as far as the screen.

    **The bound handed to the paged renderers is the promoted surface's own.** §5 is
    explicit that a routed read-only operation is performed "exactly as the promoted
    surface declares it, with that surface's own defaults and that surface's own
    bound", and routing gets no setting of its own — so ``DEFAULT_PAGE_SIZE`` is what
    a full page is measured against here, exactly as it is on the typed door.

    **A candidate listing is rendered per record rather than as a page**, because it
    is not one: an ambiguity carries what the lookup matched, and the "that is a full
    page, ask for the next" footers a listing surface prints would be an invitation
    to page through something that has no next page. What §5 forbids is rendering
    fewer candidates than the outcome carries or summarising in place of them, and
    nothing here does either.
    """
    if outcome in (RouteOutcome.AMBIGUOUS, RouteOutcome.AMBIGUOUS_TRUNCATED):
        _render_routed_candidates(operation, listing)
        return
    match operation:
        case RoutableOperation.QUESTIONS:
            _render_questions(
                _routed_records(operation, listing, Question),
                (),
                limit=DEFAULT_PAGE_SIZE,
                offset=0,
            )
        case RoutableOperation.RECENT_READS:
            _render_reads(
                _routed_records(operation, listing, SourceReadRecord), limit=DEFAULT_PAGE_SIZE
            )
        case RoutableOperation.RECENT_INVOCATIONS:
            _render_invocations(
                _routed_records(operation, listing, RecordedInvocation), limit=DEFAULT_PAGE_SIZE
            )
        case RoutableOperation.RECENT_DECISIONS:
            _render_decisions(
                _routed_records(operation, listing, PermissionDecision), limit=DEFAULT_PAGE_SIZE
            )
        case RoutableOperation.STANDING_GRANTS:
            _render_standing(_routed_records(operation, listing, SourceGrant))
        case RoutableOperation.SPEND_TOTALS:
            _render_spend(_routed_records(operation, listing, SpendTotal))
        case _:  # pragma: no cover - unreachable by RoutedOperation's own validator
            # A confirm-owed operation carries a listing on exactly the two ambiguous
            # outcomes, which returned above. Reaching here would mean the validator
            # admitted a confirm-owed `PERFORMED` with a listing, which it does not.
            raise AssertionError(f"{operation.value} carries no listing on {outcome.value}")


def _render_routed_candidates(operation: RoutableOperation, listing: RoutedListing) -> None:
    """Render what an ambiguous lookup matched, whole (ADR-0197 §5).

    **Every candidate, and never a summary of them.** §5's last clause is "no surface
    renders fewer candidates than the outcome carries or summarises in place of
    them", which is ADR-0186 §7's rule for a trail row applied to a candidate
    listing. A narrow terminal therefore gets a longer screen, not a shorter list.

    **A belief candidate is rendered in full, warrant included**, for the reason
    :func:`_render_belief` states: the user is about to say which of these to
    destroy, and the citations are the warrant they are judging.
    """
    match operation:
        case RoutableOperation.FORGET | RoutableOperation.GUARD | RoutableOperation.UNGUARD:
            # ADR-0217 §7's acts resolve over `forget`'s own candidate set, so they
            # render through its arm: the user is choosing among beliefs, and the
            # warrant is as much a part of judging which one to place as it is of
            # judging which one to destroy.
            for belief in _routed_records(operation, listing, Belief):
                _render_belief(belief)
        case RoutableOperation.FORGET_QUESTION:
            for question in _routed_records(operation, listing, Question):
                _render_question(question)
        case RoutableOperation.REVOKE:
            for grant in _routed_records(operation, listing, SourceGrant):
                console.print(f"\n  [bold cyan]{_safe(grant.source)}[/]")
                console.print(f"    [green]allowed for[/] {_scope_phrase(grant.scope)}")
                console.print(f"    [dim]granted {_when(grant.decided_at)}[/]")
        case _:  # pragma: no cover - unreachable by RoutedOperation's own validator
            # A read-only operation admits exactly `PERFORMED`, `UNRECORDED` and
            # `FAILED` (ADR-0197 §8), so neither ambiguous outcome reaches it.
            raise AssertionError(f"{operation.value} is never ambiguous")


def _render_operation_confirmation(card: OperationConfirmation) -> None:
    """Show what a routed operation would do, before it is answered (ADR-0197 §7).

    **This is not a** :class:`~ai_assistant.core.types.Confirmation` **and it is not
    rendered as one.** A routed act has no tool, no arguments and no policy ruling,
    so three of that type's four content members would have to be filled with
    something invented — the falsehood-in-durable-state failure ADR-0170 §3 refused,
    arriving in a value a user reads. What is on screen instead is exactly what §7
    says the card carries: the operation, and the resolved subject as a typed value.

    **No model-written text reaches it.** The router's query is not shown, the
    operation is an enum member, and every word around the subject is selected by
    that member — which is what makes a card a person can trust to describe the act
    rather than to describe how the act was asked for.

    **The subject is rendered by the renderer this adapter already has**, and for
    ``forget`` that renderer is the whole ADR-0073 §5 ceremony (:func:`_render_forget_prompt`):
    the belief in full, the band-appropriate warning, what destroying it costs, and
    the window between the show and the delete. ADR-0197 §7's last clause binds that
    ceremony to the routed ``forget`` "whole, including its band-appropriate warning
    and its ``--yes`` idiom, which renders before acting rather than skipping the
    render" — so this runs before the answer is collected on every path.

    **``revoke`` and ``forget_question`` get a card here although the typed door
    gives them none, and that is ADR-0197 §3 rather than a contradiction.** ADR-0102
    §4 keeps a prompt out of ``assistant revoke`` because nothing may stand between a
    user and their own remedy, and ADR-0078 §1 keeps one out of
    ``assistant forget-question`` because a question is not a belief. Neither reason
    reaches here: what §7 guards is not the risk of the operation but the fact that a
    **model** selected it and its subject from a sentence, and "the direction of a
    write does not change its tag".
    """
    if card.operation is RoutableOperation.FORGET:
        for belief in _routed_records(card.operation, card.subject, Belief):
            _render_forget_prompt(belief)
        return
    console.print(f"\n[bold yellow]About to {_ROUTED_ASKED[card.operation]}[/]")
    if card.operation in _PLACEMENT_ACT_NOTE:
        # The belief without ADR-0073 §5's destruction ceremony, which would be false
        # here: an act changes who may receive the record and destroys nothing. What
        # the reader is judging is still the belief, warrant included, because that is
        # what they are about to change the audience of.
        for belief in _routed_records(card.operation, card.subject, Belief):
            _render_belief(belief)
        console.print(_PLACEMENT_ACT_NOTE[card.operation])
        return
    if card.operation is RoutableOperation.REVOKE:
        for grant in _routed_records(card.operation, card.subject, SourceGrant):
            console.print(f"\n  [bold cyan]{_safe(grant.source)}[/]")
            console.print(f"    [green]currently allowed for[/] {_scope_phrase(grant.scope)}")
            console.print(f"    [dim]granted {_when(grant.decided_at)}[/]")
        console.print(
            "\n  This stops me reading that source from now on. It destroys nothing "
            "I have already learned from it, and you can grant it again."
        )
        return
    for question in _routed_records(card.operation, card.subject, Question):
        _render_question(question)
    console.print(
        "\n  This destroys the record of having been asked. Nothing I believe "
        "changes, and you can tell me the same thing again yourself."
    )


def _confirm_operation(_card: OperationConfirmation) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    :func:`_drive_turn` renders the card through :func:`_render_turn` before it
    reaches here, so rendering again would show the belief twice (I/O; ADR-0042 §6).
    The counterpart of :func:`_confirm` on the routed side.
    """
    return typer.confirm("Proceed?", default=False)


def _render_conversation_footer(outcome: TurnOutcome) -> None:
    """Name the conversation this turn ran under, so the user can continue it.

    The id is opaque and carries no user content, so showing it discloses nothing;
    it is neutralised for this terminal like any other engine-supplied string
    (``_safe``, ADR-0042 §4). ``None`` only where nothing could be resolved — a
    recovered resumption whose park predates capture, or whose conversation was
    deleted — and there is then no id to offer.
    """
    if outcome.conversation_id is None:
        return
    console.print(
        f"\n[dim]Conversation:[/] {_safe(outcome.conversation_id)}  "
        f"[dim](continue with: assistant ask --conversation "
        f"{_safe(outcome.conversation_id)} ...)[/]"
    )


def _render_conversations(
    page: tuple[ConversationSummary, ...], *, limit: int, offset: int
) -> None:
    """Render one page of conversations (ADR-0074 §2).

    Ordered by last activity, which is the store's contract and not re-sorted here.
    **No total is shown**, and none is available to show: "is there more" is
    answered by asking for the next page, exactly as the belief listing answers it.
    """
    if not page:
        console.print("[dim]No conversations yet — 'assistant ask' starts one.[/]")
        return
    console.print(f"[bold]{len(page)} conversation(s)[/], most recently active first.")
    for conversation in page:
        console.print(f"\n  [bold cyan]{_safe(conversation.id)}[/]")
        console.print(f"  [dim]Started:[/] {_when(conversation.started_at)}")
        console.print(f"  [dim]Last active:[/] {_when(conversation.last_active_at)}")
        if conversation.last_turn_at is None:
            console.print("  [dim]No turn has been recorded in it yet.[/]")
        else:
            console.print(f"  [dim]Last recorded turn:[/] {_when(conversation.last_turn_at)}")
    if limit and len(page) == limit:
        console.print(
            f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
        )


def _render_forget_conversation_prompt(digest: ConversationDigest) -> None:
    """Show what a conversation deletion will destroy (ADR-0074 §8, ADR-0073 §5).

    **The count and span, not every turn.** A transcript at a prompt is not
    something a person can judge, and showing nothing would be taking consent for
    something unseen. The count is of turns *recorded*: one whose episode has since
    expired or been deleted still happened, and saying otherwise would understate
    what is being destroyed.
    """
    console.print("\n[bold yellow]About to forget this conversation[/]")
    console.print(f"  [bold cyan]{_safe(digest.id)}[/]")
    console.print(f"  [dim]Started:[/] {_when(digest.started_at)}")
    if digest.last_turn_at is None:
        console.print("  [dim]Turns recorded:[/] none")
    else:
        console.print(
            f"  [dim]Turns recorded:[/] {digest.recorded_turns}, "
            f"the last at {_when(digest.last_turn_at)}"
        )
    console.print(
        "\n  [yellow]This destroys the conversation and every episode it recorded: "
        "they leave memory, this listing, and any export.[/]"
    )
    console.print(
        "  [dim]Turns already deleted or past their retention window stay gone; "
        "nothing is restored.[/]"
    )


def _render_no_such_conversation(conversation_id: str) -> None:
    """Report an id that names no conversation this surface can show (ADR-0074 §1, §8).

    Unknown, already deleted, or reclaimed after its retention horizon passed — all
    three look the same from here on purpose, because a surface that distinguished
    them would report on conversations it is meant to have forgotten.
    """
    console.print(
        f"[yellow]No conversation has the id[/] {_safe(conversation_id)}. "
        "It may never have existed, or you may have deleted it already — "
        "'assistant conversations' lists the ones that are still here."
    )


def _confirm_forget_conversation(_digest: ConversationDigest) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    The conversation-scoped sibling of :func:`_confirm_forget` (I/O; ADR-0042 §6).
    Defaults to **no**, for its reason: the question is about destroying something
    irreversibly, and more of it.
    """
    return typer.confirm("Forget it?", default=False)


def _render_transcript_notice() -> None:
    """State what an archive read is, unasked (ADR-0225 §8).

    §8 requires it in terms: "A surface rendering archive content states, without
    being asked, that what it shows is a record of what was said and not what the
    assistant believes or retrieves." It is printed on **every** archive read, an
    empty page included, rather than only when rows come back — a notice a user sees
    once and then stops seeing is a notice they learn to skip, and the sentence is
    true of an empty result too.

    It is not a disclaimer about accuracy. What it tells the user is which store they
    are looking at: nothing here reaches a reply, because nothing on the turn path can
    read it (§4).
    """
    console.print(
        "[dim]A record of what was said — your words and mine, as they were said. "
        "Not what I believe, not what I retrieve, and not evidence for anything: "
        "nothing here reaches a reply.[/]"
    )


def _render_archive_size(size: TranscriptArchiveSize) -> None:
    """Show the archive's two figures beside a read, unasked (ADR-0225 §6).

    **Both figures, never one and never their difference.** §6 has them answer
    different questions and allows them to disagree — ``entries`` is what the reads
    would return, ``stored_bytes`` is what is on the disk with hidden and unreclaimed
    entries included — and "a report that netted the two would hide exactly the growth
    the cap exists to catch". So they are printed side by side, unnetted, with no
    commentary reconciling them.

    This exists because ADR-0162 §5's lesson is that a trigger with no instrument
    never fires: ADR-0225 §6 sets no size cap and defers one, and the figure that
    would fire it is on the screen every time the user looks.
    """
    turns = "turn" if size.entries == 1 else "turns"
    console.print(
        f"[dim]Archive:[/] {size.entries:,} {turns} readable, "
        f"{_stored_bytes(size.stored_bytes)} on disk."
    )


def _stored_bytes(count: int) -> str:
    """Render a byte total exactly, with a rounded figure beside it where it helps.

    The exact count is always shown and is never replaced by the rounded one: what
    ADR-0225 §6 puts on the screen is a measurement, and rounding it away at the one
    surface that reports it would blunt the instrument the section exists to provide.
    """
    if count < _MIB:
        return f"{count:,} bytes"
    return f"{count:,} bytes ({count / _MIB:.1f} MiB)"


def _render_transcript_hits(page: tuple[TranscriptHit, ...], *, limit: int, offset: int) -> None:
    """Render one page of search hits (ADR-0225 §7).

    A hit is a taste and an address, never the turn: §7 splits the read in two so that
    a search matching hundreds of turns stays readable and the excerpt bound stays
    meaningful. ``elided`` is rendered rather than dropped, so a user can tell a whole
    short turn from a window cut out of a long one and knows when ``show`` will tell
    them more.
    """
    if not page:
        console.print("[dim]Nothing matched.[/]")
        return
    console.print(f"[bold]{len(page)} match(es)[/], newest first.")
    for hit in page:
        console.print(f"\n  [bold cyan]{_safe(hit.address)}[/]")
        console.print(f"  [dim]When:[/] {_when(hit.occurred_at)}")
        console.print(f"  [dim]Conversation:[/] {_safe(hit.conversation_id)}")
        console.print(f"  {_safe_prose(hit.excerpt)}")
        if hit.elided:
            console.print(
                "  [dim]Shortened to fit — 'assistant transcript show' reads the turn whole.[/]"
            )
    if len(page) == limit:
        console.print(
            f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
        )


def _render_transcript_entries(
    page: tuple[TranscriptEntry, ...], *, limit: int, offset: int, empty: str
) -> None:
    """Render one page of whole entries, for both enumerating reads (ADR-0225 §7).

    Whole, and elided nowhere: §7 gives the excerpt bound to the search alone and has
    the other three reads "return entries whole, and elide, truncate and summarise
    nothing". The two callers differ only in what they say about an empty page — one
    is a conversation nothing is held under, the other an archive holding nothing at
    all — which is a sentence rather than a shape.
    """
    if not page:
        console.print(f"[dim]{empty}[/]")
        return
    console.print(f"[bold]{len(page)} turn(s)[/].")
    for entry in page:
        _render_transcript_entry(entry)
    if len(page) == limit:
        console.print(
            f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
        )


def _render_transcript_entry(entry: TranscriptEntry) -> None:
    """Render one turn whole: its address, when it was, and both halves (ADR-0225 §1).

    **An absent half is stated rather than skipped**, because the two absences mean
    different things and a reader can act on both: no user words is a turn the system
    drove on its own — a parked step's resolution, whose utterance was archived at its
    own address (§1) — and no reply is a turn that produced none.

    The disposition is rendered for the reason §1 carries it: without it "a turn that
    parked reads in the transcript as a question nobody answered".
    """
    console.print(f"\n  [bold cyan]{_safe(entry.address)}[/]")
    console.print(f"  [dim]When:[/] {_when(entry.occurred_at)}")
    console.print(
        f"  [dim]Conversation:[/] {_safe(entry.conversation_id)} "
        f"[dim]turn[/] {entry.ordinal} [dim]·[/] {_safe(entry.disposition.value)}"
    )
    if entry.asked is None:
        console.print("  [dim]You said nothing on this turn.[/]")
    else:
        console.print(f"  [bold]You:[/] {_safe_prose(entry.asked)}")
    if entry.replied is None:
        console.print("  [dim]I said nothing on this turn.[/]")
    else:
        console.print(f"  [bold]Me:[/] {_safe_prose(entry.replied)}")


def _render_no_such_transcript_entry(address: str) -> None:
    """Report an address nothing is held at (ADR-0225 §3, §6).

    Never held, past a finite ``transcript_archive_retention``, or destroyed — all
    three look the same from here on purpose, exactly as ``_render_no_such_conversation``
    conflates its own three: a surface that told them apart would report on transcripts
    it is meant to have evicted.
    """
    console.print(
        f"[yellow]No transcript is held at[/] {_safe(address)}. "
        "It may never have existed, it may have passed the archive's retention window, "
        "or you may have destroyed it already."
    )


def _render_forget_transcript_prompt(address: str, entry: TranscriptEntry | None) -> None:
    """Show what destroying one entry will destroy (ADR-0225 §5, ADR-0073 §5).

    Where the entry reads back, it is shown whole — it is one turn, which is exactly
    what a person can judge at a prompt. Where it does not, the prompt says so and
    still offers the destruction, because ADR-0225 §6 has the destroys reach what the
    reads hide and a refusal here would put a hidden turn beyond the user's reach for
    good.
    """
    console.print("\n[bold yellow]About to destroy this turn's transcript[/]")
    if entry is None:
        console.print(f"  [bold cyan]{_safe(address)}[/]")
        console.print(
            "  [dim]Nothing readable is held at that address. It may be past the archive's "
            "retention window, in which case this still destroys it.[/]"
        )
    else:
        _render_transcript_entry(entry)
    console.print(
        "\n  [yellow]This destroys the transcript of that turn and nothing else: "
        "what I believe is untouched, and 'assistant forget' is the command for that.[/]"
    )


def _render_forget_transcript_conversation_prompt(
    conversation_id: str, page: tuple[TranscriptEntry, ...]
) -> None:
    """Show what destroying a conversation's transcript will destroy (ADR-0225 §5).

    **The page is shown and is not claimed to be the whole of it.** The read is paged
    and a finite retention hides entries the destroy still reaches, so there is no
    honest total to render — and ADR-0074 §8's own ceremony shows a count because
    ``ConversationDigest`` carries one, which the archive does not. What this states
    instead is the *scope*, in words: every turn of this conversation. Inventing a
    count from the first page would be worse than not showing one, because the user
    would read it as the number about to go.
    """
    console.print("\n[bold yellow]About to destroy this conversation's transcript[/]")
    console.print(f"  [bold cyan]{_safe(conversation_id)}[/]")
    if not page:
        console.print(
            "  [dim]Nothing readable is held under that id. Turns past the archive's "
            "retention window are not shown here and are still destroyed.[/]"
        )
    else:
        console.print(f"  [dim]The first {len(page)} turn(s) held under it:[/]")
        for entry in page:
            _render_transcript_entry(entry)
    console.print(
        "\n  [yellow]This destroys every turn of this conversation's transcript — "
        "including any not shown above, and any the archive's retention window is "
        "hiding. What I believe is untouched.[/]"
    )


def _confirm_forget_transcript(_entry: TranscriptEntry | None) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    :func:`_confirm_forget_conversation`'s sibling for the archive (I/O; ADR-0042 §6),
    and it defaults to **no** for the same reason: the question is about destroying
    something irreversibly.
    """
    return typer.confirm("Destroy it?", default=False)


def _confirm_forget_transcript_conversation(_page: tuple[TranscriptEntry, ...]) -> bool:
    """Read the human's yes/no for the conversation-scoped destroy, having shown it."""
    return typer.confirm("Destroy the whole transcript?", default=False)


def _render_disposition(disposition: Disposition, tool_id: str | None) -> None:
    """Render the permission gate's verdict on the driven step (ADR-0042 §3).

    **Only the verdict.** ``EXECUTED`` says the call was authorised and handed to
    the executor, not that the executor succeeded — its own documentation delegates
    that downward — so :func:`_render_step` consults the step's record before
    reaching for this, and "Done." is printed only for a step that really is done
    (ADR-0084 §8).

    **``EGRESS_UNBINDABLE`` says the call could not be described and names nothing
    about it** (ADR-0152 §9, §11). It is not ``DENIED`` — no policy refused, because
    the seam runs before a decision exists — and a line that read as a refusal would
    be a falsehood about the user's own policy. It names no tool, no argument, no
    recipient and no reference: ADR-0152 §11 binds the *seam's* message, and this
    adapter is handed a bare verdict with no field carrying any of them anyway.

    **``AWAITING_CONFIRMATION`` is the one member deliberately absent**, and after
    ADR-0145 §4's addition it is the only one: the confirm flow renders the parked
    action itself (:func:`_render_confirmation`), from the content a bare verdict
    does not carry, so a line here would either duplicate it or contradict it. The
    mapping is read with ``.get`` rather than indexed for that member alone — a
    miss prints nothing, which is what a step whose rendering lives elsewhere
    wants.

    **``INVALID_PARAMETERS`` says only that nothing established the arguments as
    acceptable** (#1113), and the hedge is load-bearing rather than cautious prose.
    ADR-0145 §4 gives the member *one* definition and **two** causes: every capable
    candidate reported violations, or an evaluation raised. Only the first
    establishes that the arguments do not fit; on the second §7 is explicit that "a
    raise establishes no such fact", and the arguments may well have satisfied every
    schema. A line saying they did not fit would therefore be false on one of the
    two paths that print it — the same defect as calling an ``INDETERMINATE`` step
    failed (:func:`_step_headline`), one disposition over. So the wording is
    ``Disposition.INVALID_PARAMETERS``'s own: *not established as acceptable*, which
    is true of both.

    Two further constraints shape it. ADR-0145 §8 forbids any rendering from
    carrying an argument value *or key*, so nothing about the parameters is echoed;
    and the violations that would say which constraint was missed stop at
    ``orchestration``'s ``StepDisposition`` — :class:`StepOutcome`, the only thing
    this adapter is handed, has no field for them, and giving it one is the wire
    change ADR-0145 §14 parks as #1106. So the line is a fixed phrase rather than a
    report, and it names no tool: the disposition is reached with the candidate set
    emptied by ADR-0144 §7's eligibility filter, so ``tool_id`` is ``None`` and
    there is no "selected tool" to name. It reads like ``AMBIGUOUS_CAPABILITY``
    because ADR-0145 §4 gives it that shape — nothing was committed, nothing was
    asked, and the step stays ``PENDING`` for a re-plan with corrected arguments.
    """
    tool = _safe(tool_id) if tool_id is not None else "the selected tool"
    messages = {
        Disposition.EXECUTED: f"[green]Done.[/] Ran {tool}.",
        Disposition.DENIED: "[red]Declined.[/] The policy did not permit this action.",
        Disposition.NO_CAPABLE_TOOL: "[dim]No tool is available for this step yet.[/]",
        Disposition.AMBIGUOUS_CAPABILITY: "[dim]Several tools could do this; none was chosen.[/]",
        Disposition.INVALID_PARAMETERS: (
            "[dim]This step's arguments were not established as acceptable to any tool that "
            "could have done it; nothing was run.[/]"
        ),
        Disposition.EGRESS_UNBINDABLE: (
            "[dim]This step's outbound call could not be described, so nobody was asked "
            "and nothing was sent.[/]"
        ),
    }
    message = messages.get(disposition)
    if message is not None:
        console.print(message)


def _render_learn(outcome: LearnOutcome) -> None:
    """Render what one piece of feedback did to memory (ADR-0042 §6).

    A short human-readable confirmation: a header counting the updates memory made,
    then one line per proposal naming the ruling and its reason. The reason is
    engine-supplied data, so it is neutralised for this terminal like any other
    (``_safe``, ADR-0042 §4). Feedback that proposed no update at all is reported as
    such rather than as a silent success.

    A **deferral** gets its line from :func:`_deferred_message`, because since
    ADR-0078 there is no single honest sentence for one: a question the user can go
    and answer, a question already asked, a full queue, and secret-tier data that is
    still not answerable are four outcomes, and the line has to say which.
    """
    if not outcome.results:
        console.print("[dim]Noted — nothing in that needed a memory update.[/]")
        return
    console.print(
        f"[green]Learned.[/] Folded {len(outcome.results)} update(s) into memory "
        f"({outcome.stored} stored)."
    )
    for summary in outcome.results:
        console.print(f"  - {_message_for(summary)} [dim]({_safe(summary.reason)})[/]")


def _message_for(summary: IngestSummary) -> str:
    """The one line describing what became of one proposal (ADR-0078 §10 item 9)."""
    if summary.decision is LearnDecision.DEFERRED:
        return _deferred_message(summary.queued)
    return _LEARN_MESSAGES[summary.decision]


def _deferred_message(queued: QueuedQuestion | None) -> str:
    """What a deferred ruling means for the user, by what the queue did (ADR-0078 §7).

    Four sentences, and the split is the honesty rule this surface is built on. Until
    ADR-0078 there was one line — "this needs review, which cannot be done from here
    yet" — and it was true: nothing persisted a deferred proposal, so pointing the
    user at a follow-up would have implied a flow that did not exist. That line is
    now **false for the arms ADR-0078 closes** and still **true for the one it does
    not**, so it is kept for exactly that one:

    * **queued** — the question is waiting; name it and name the verb that answers it.
      This is the reach that closes issue #423's own scenario: the user submits
      feedback, is told it is deferred, and is pointed at the answer.
    * **already asked** — an existing question stands in the way, and *which and in
      what state* decides what to say (:data:`_SUPPRESSOR_MESSAGES`).
    * **queue full** — there is no question to name, so the line names the **queue**:
      answer or clear some of what is waiting, then submit again. Reported rather
      than swallowed, which is the branch an implementation is most likely to leave
      silent because nothing raises.
    * **not queuable** — secret-tier data, which ADR-0004 §3 forbids a durable file,
      so nothing was queued and there is nothing to answer. It keeps the existing
      line and the existing reason: one message covering this and the cases above
      would tell a user to go answer a question that was never asked.

    ``None`` cannot arise for a deferral — the façade attaches a
    :class:`~ai_assistant.orchestration.QueuedQuestion` to every one — and is
    rendered as the honest non-answerable line rather than as an answerable one, so a
    future gap fails safe.
    """
    if queued is None:
        return _NOT_ANSWERABLE
    match queued.outcome:
        case QueueOutcome.NOT_QUEUABLE:
            return _NOT_ANSWERABLE
        case QueueOutcome.QUEUED:
            return (
                f"Not stored yet — I have a question for you: "
                f"[bold cyan]{_safe(queued.question_id or '')}[/] "
                f"[dim](see it with: assistant questions)[/]"
            )
        case QueueOutcome.ALREADY_ASKED:
            state = queued.question_state
            lead = (
                _SUPPRESSOR_MESSAGES[state]
                if state is not None
                else "Not stored — a matching question stands in the way:"
            )
            return f"{lead} [bold cyan]{_safe(queued.question_id or '')}[/]"
        case QueueOutcome.QUEUE_FULL:
            return (
                "Not stored — the question queue is full, so this could not be parked. "
                "Answer or forget some of what is waiting ('assistant questions'), then "
                "teach me this again."
            )
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(queued.outcome)


def _render_observation(report: ObservationReport) -> None:
    """Render one observation pass (ADR-0077 §8, §9.8).

    Four things the user is owed, in this order:

    1. **what was read, and by which model.** ADR-0013 §6 records "which provider
       answered is not currently reported, and should be once there is an interface
       to report it"; this is that interface, for the one call where it matters
       most — a model reading back the transcript. The route is *absent* when the
       observer was never called, and is then not claimed.
    2. **every belief proposed**, whether or not it was stored, with the evidence
       behind it and the gate's ruling. A proposal the gate refused is as
       informative as one it kept.
    3. **the deferrals**, in full and by name. ``ASK_USER`` writes nothing and
       nothing persists it (ADR-0077 §4, #423), so if this rendering omitted the
       candidate the deferral would be invisible — which is the gap the interim is
       there to close. The note under a deferred proposal says outright that it is
       not queued.
    4. **what was thrown away**, so silence never reads as "there was nothing to
       learn" (ADR-0022 §3).
    """
    if report.conversation_id is None:
        console.print("[dim]No conversation to observe yet — have one first with[/] assistant ask.")
        return
    if report.route is None:
        console.print(
            f"[dim]Nothing to observe in conversation[/] {_safe(report.conversation_id)}[dim]: "
            "none of its recent turns still has a recorded episode, so no model was asked.[/]"
        )
        return
    console.print(
        f"[bold]Observed[/] {report.episodes_read} episode(s) from conversation "
        f"{_safe(report.conversation_id)}, read by [bold cyan]{_safe(report.route)}[/]."
    )
    if not report.proposals:
        console.print("[dim]Nothing in them was worth believing durably.[/]")
    else:
        console.print(
            f"{len(report.proposals)} belief(s) proposed, {report.stored} stored. "
            "[dim]See them with[/] assistant beliefs[dim].[/]"
        )
        for proposal in report.proposals:
            _render_observed_proposal(proposal)
    _render_observation_discards(report)


def _observed_message(decision: LearnDecision) -> str:
    """The ruling line for one observed proposal (ADR-0077 §8, ADR-0078 §7).

    :data:`_LEARN_MESSAGES` no longer carries ``DEFERRED``, because the ``learn``
    surface says which of four things the queue did and reads that off the result. An
    **observation** cannot: ADR-0078 §7 is explicit that "an observer proposal refused
    at the cap is reported to the observing stage and no further; what that stage's
    own result carries is ADR-0077's to decide, not this ADR's to specify from
    outside", so ``ObservationReport`` is deliberately not widened here and this line
    claims nothing about the admission. It says only what is true on every branch —
    nothing was stored, and an answer is owed.
    """
    if decision is LearnDecision.DEFERRED:
        return "Not stored — it needs your answer."
    return _LEARN_MESSAGES[decision]


def _render_observed_proposal(proposal: ObservedProposal) -> None:
    """Render one proposed belief and what the gate did with it.

    The epistemic step leads the row rather than the band: every observed proposal
    is in the ``derived`` band by contract, so the band carries no information here
    while ``observed`` versus ``inferred`` is the difference between "your own words
    show this" and "I generalised from them" (ADR-0072 §3).

    **The citations are printed for whatever the write path did not keep** — a
    deferral, a rejection, a drop. ADR-0077 §4 requires a reported deferral to carry
    "the candidate's content, its citations and the policy's stated reason", and the
    reason they must be *here* is that no later view resolves them. Since ADR-0078 a
    deferred proposal **is** persisted and ``assistant questions`` shows its content,
    the reason it was deferred and what accepting it would retire — but resolving
    ``Provenance.evidence`` into readable text is ADR-0073 §10's open half of #431,
    which ADR-0078 §11 deliberately leaves there. So this is still the only rendering
    of a deferred proposal's *warrant*. A **stored** belief is not
    printed with its evidence, because it has that later view — ``assistant
    beliefs`` lists it and the forget ceremony shows the warrant in full — and
    echoing every episode behind every accepted belief would reprint the transcript
    the observation was distilled *from*.

    Engine-supplied text — the content, the rationale, the policy's reason, the id,
    a citation's content — is neutralised for this terminal like any other
    (``_safe``, ADR-0042 §4).
    """
    console.print(
        f"\n  [bold cyan]{proposal.step.value}[/] · {proposal.kind.value} · "
        f"confidence {proposal.confidence:.2f} · "
        f"from {proposal.evidence_count} episode(s)"
    )
    console.print(f"  {_safe(proposal.content)}")
    console.print(f"  [dim]Why:[/] {_safe(proposal.rationale)}")
    if not proposal.inspectable:
        _render_citations(proposal)
    if proposal.decision is None:
        console.print(f"  [yellow]Not stored:[/] {_safe(proposal.reason)}.")
        return
    console.print(
        f"  [dim]Memory:[/] {_observed_message(proposal.decision)} "
        f"[dim]({_safe(proposal.reason)})[/]"
    )
    # A deferral gets **no extra note here, and the absence is the decision**
    # (ADR-0019, ADR-0078 §7). The old note said the proposal was "gone when this
    # command ends", which was true and became false the moment the write stage
    # started parking one. Nothing may replace it, because there is nothing further
    # this adapter can honestly say: an observer's refusals stay at the observing
    # stage "and no further", so `ObservationReport` deliberately does not carry the
    # admission — widening it is ADR-0077's call, not this lane's — and every
    # replacement tried was a claim about state the report does not hold. "Go answer
    # it" is false when the queue refused it; "the queue was full" is false when the
    # question was parked on page two, answered, or lapsed. The ruling line above
    # says the one thing that holds on every branch — nothing was stored and an
    # answer is owed — and `assistant questions` documents itself.
    if proposal.record_id is not None:
        console.print(f"  [dim]id:[/] {_safe(proposal.record_id)}")


def _render_citations(proposal: ObservedProposal) -> None:
    """Render the episodes one proposal rests on (ADR-0077 §4).

    A citation the stage could not resolve is a **tombstone**, exactly as on the
    inspection surface (:func:`_render_evidence`) and for ADR-0073 §4's reason: never
    a bare id, never a silent gap. Here it means the evidence went away between
    selection and the write, which is also why nothing was stored.
    """
    if not proposal.evidence:
        return
    console.print("  [dim]From:[/]")
    for item in proposal.evidence:
        if item.content is None:
            console.print("    [yellow]—[/] [dim]an episode stood here and is gone.[/]")
        else:
            console.print(f"    - {_safe(item.content)}")


def _render_observation_discards(report: ObservationReport) -> None:
    """Say what was thrown away getting here, or that nothing was (ADR-0077 §4).

    Reported rather than left silent, because "no beliefs" and "ten beliefs, all
    unusable" are the two states this counting exists to tell apart — silence
    reading as success is the failure ``memory_degraded`` was added to prevent
    (ADR-0022 §3). The three counts are kept apart because they answer different
    questions: what the model emitted and the producer could not use, what the
    producer dropped to stay inside its bound, and what the write path refused
    because the evidence had gone.
    """
    if not report.discarded:
        return
    console.print(
        f"\n[dim]Discarded {report.discarded}: "
        f"{report.discarded_unusable} unusable, "
        f"{report.discarded_over_limit} over the per-pass limit, "
        f"{report.dropped_unsupported} whose evidence went away before it could be stored.[/]"
    )


def _render_questions(
    waiting: tuple[Question, ...],
    stranded: tuple[Question, ...],
    *,
    limit: int,
    offset: int,
) -> None:
    """Render the answerable questions, then the interrupted ones (ADR-0078 §8).

    Two sections, and the second is never folded into the first. **No total is shown**
    and none is available: "is there more" is answered by asking for the next page,
    exactly as the belief and conversation listings answer it.
    """
    if not waiting and not stranded:
        console.print("[dim]Nothing is waiting on your answer.[/]")
        return
    if waiting:
        console.print(f"[bold]{len(waiting)} question(s)[/] waiting on your answer, oldest first.")
        for question in waiting:
            _render_question(question)
        if limit and len(waiting) == limit:
            console.print(
                f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
            )
    if stranded:
        console.print(
            f"\n[bold yellow]{len(stranded)} interrupted answer(s).[/] "
            "An answer to each of these was begun and its outcome was never recorded."
        )
        for question in stranded:
            _render_question(question)


def _render_question(question: Question) -> None:
    """Render one question with everything ADR-0078 §8 requires it to convey.

    Six things, and each is there because leaving it out would misrepresent what the
    user is being asked:

    * **what accepting would have the assistant believe**, and the band it *would*
      enter — worded as a conditional, never as a belief held. A pending question is
      not a belief of any band (§1), so "would be held as" rather than "is";
    * **why the user is being asked** — the ruling's own non-optional reason;
    * **where the proposal came from** (:func:`_proposal_origin`), which ADR-0189 §9
      puts on this renderer by name: §4 binds "every surface that renders an attested
      belief, question or retirement", and a question is the projection the first
      attested proposals actually reach, so a lane that updated only the belief
      explanation would have left the surface §4 was written for unchanged;
    * **what accepting would retire** (:func:`_render_retirements`), which is not
      decoration but the exact scope the answer authorises;
    * **when it was asked and when it stops being answerable**;
    * for an interrupted question, that an answer was begun and its outcome is not
      recorded, plus the two recovery steps **in order** — and deliberately not a
      retry, because the system does not know whether the write landed and a verb
      implying it does would be the one dishonest line on this surface;
    * where an interrupted answer already raised a follow-up, that row **rendered by
      its own state** (:func:`_render_successor`): only a waiting one is something the
      user can go and answer.

    Engine-supplied text is neutralised for this terminal (``_safe``, ADR-0042 §4).
    The band, kind and state are this system's own closed vocabularies.
    """
    console.print(f"\n  [bold cyan]{_safe(question.id)}[/]")
    console.print(f"  [bold]{_safe(question.content)}[/]")
    console.print(
        f"  [dim]Would be held as:[/] {question.band.value} {question.kind.value} "
        f"[dim](not held yet — I am asking first)[/]"
    )
    console.print(f"  [dim]Why I am asking:[/] {_safe(question.reason)}")
    console.print(f"  [dim]Proposed because:[/] {_safe(question.rationale)}")
    origin = _proposal_origin(question)
    if origin:
        console.print(f"  [dim]Where it came from:[/] {origin}")
    _render_retirements(question)
    console.print(f"  [dim]Asked:[/] {_when(question.asked_at)}")
    if question.expires_at is None:
        console.print("  [dim]Answerable:[/] indefinitely")
    else:
        console.print(f"  [dim]Answerable until:[/] {_when(question.expires_at)}")
    if question.state is QuestionState.INTERRUPTED:
        console.print(
            "  [yellow]An answer to this was begun and its outcome was never recorded.[/] "
            "I cannot tell you whether the change landed, so there is nothing to retry."
        )
        # The step is numbered either way: what a lossy id costs is the copyable
        # command, never the recovery step it belongs to.
        _print_hint(
            f"  [dim]1.[/] Dispose of it: assistant forget-question {_argument(question.id)}"
            if _is_pasteable(question.id)
            else f"  [dim]1.[/] Dispose of it with 'assistant forget-question'. "
            f"{_uncopyable('Its id')}"
        )
        console.print(
            "  [dim]2.[/] Check 'assistant beliefs', and use 'assistant learn' again if "
            "the correction is missing."
        )
    else:
        _print_hint(
            f"  [dim]Answer with:[/] assistant answer {_argument(question.id)} "
            f"--accept  [dim]|[/]  --reject"
            if _is_pasteable(question.id)
            else "  [dim]Answer with:[/] 'assistant answer', with --accept or --reject. "
            f"{_uncopyable('Its id')}"
        )
    _render_successor(question)


def _proposal_origin(question: Question) -> str:
    """Where the **proposal** came from, or nothing to say (ADR-0189 §4, §9).

    Both fields read here describe the record that would be written if the question
    were accepted — the same reading ``band`` already has on this type — and describe
    **no entry in ``retires``** (ADR-0189 §2). Each retirement answers for itself
    through its own warrant, which :func:`_retirement_origin` renders, and the two must
    not be confused: a question proposing the user's own assertion routinely retires an
    attested calendar line, so borrowing one answer for the other would mislabel both.

    **The attested arm is why §9 names this renderer.** A pending question is not a
    belief of any band, so nothing here says the proposal *is* held — but where it
    would be attested, §4's first clause requires the reporting source named and the
    instant it said the fact was current stated on that source's clock, and this is the
    only place on this surface that can do it.

    The derived arm carries §4's third clause about the *warrant*, never about the
    content — see :func:`_outside_warrant`, whose prohibition applies here unchanged.

    **The band selects the arm, and an attestation's presence never does.** ADR-0189 §2
    adds no cross-field validator to this type, so ``Question(band=ASSERTED,
    attestation=…)`` is model-valid — and a renderer keyed on the attestation would
    introduce the user's own word as a connected source's report. That is the laundering
    ADR-0072 §4 forbids in its own words: classification is keyed on the source and
    never on a decoration, so "nothing may acquire the standing of a band it is not in
    by decorating itself". The band is the classifier here as it is everywhere else, so
    this matches on it, is total over it, and says nothing at all about an attestation
    carried outside the attested band.

    The attested-with-no-attestation arm gets the honest sentence :func:`_why` gives its
    own, for the same reason: this projection is not what dropped the fact, so "not
    recorded" would err in the direction ADR-0073 §4 forgives least — and saying nothing
    would leave the one band whose whole purpose is provenance silent about it.

    Args:
        question: The question being rendered.

    Returns:
        The clause, or the empty string where the proposal's origin adds nothing the
        band has not already said.
    """
    match question.band:
        case BeliefBand.ATTESTED:
            if question.attestation is None:
                return (
                    "a source you connected reported it, and what reached me here does "
                    "not name that source or say when it spoke."
                )
            return (
                f"a connected source reported it — {_safe(question.attestation.reported_by)}, "
                f"which said this was current as of "
                f"{_when(question.attestation.reported_at)}, on that source's own clock."
            )
        case BeliefBand.DERIVED:
            if question.rests_on_recorded_external_content:
                return (
                    "I worked it out, and some of what I worked it out from came from a "
                    "connected source rather than from you."
                )
            return ""
        case BeliefBand.ASSERTED:
            return ""
        case _:  # pragma: no cover - exhaustive
            assert_never(question.band)


def _retirement_origin(warrant: Warrant | None) -> tuple[str, str]:
    """How a retired record's content is introduced, and what is said about it (§4).

    ADR-0189 §4 rules three arms over a :class:`~ai_assistant.core.types.Retirement`,
    and the distinction between them is the whole of what #673 asked for. Before
    ``warrant`` existed this surface rendered attacker-authorable calendar text under
    *"Accepting would retire:"* with **no origin marker at all** — a third party's
    sentence presented on the assistant's authority, at the one screen where the user
    is deciding. ADR-0098 §7 names that as the failure escalation is supposed to
    prevent: "Escalating to the user is not a mitigation if the escalation is where
    the attacker's sentence is read as ours."

    * **Attested** — the content **is** presented as third-party content, which is
      ADR-0098 §7's first clause satisfiable for the first time, and the source and
      the instant it spoke are named beside it (ADR-0189 §4's first clause read one
      projection over).
    * **Asserted** — the content is the user's own word (ADR-0038 §1a) and is **not**
      third-party. §4 is explicit that no surface presents it as such.
    * **Derived** — the content is this system's own sentence, likewise not
      third-party; where its *warrant* rests on recorded external content that fact is
      conveyed about the warrant and never about the words.

    An earlier draft of ADR-0189 ruled the third-party presentation unconditionally
    and architecture review caught it on round 3, because it would have rendered a
    retirement of the user's own assertion as somebody else's words. The band is what
    tells the three apart, and the band is inside ``warrant`` rather than on the
    ``Retirement``, which is why this reads it there (§4).

    **The lead comes before the content rather than after it**, because a marker a
    user reads *after* the sentence it qualifies has already let the sentence land as
    ours — and this is a confirmation prompt, where the whole point is that they are
    deciding while they read.

    **The ``None`` arm is off-contract and is still answered.** ADR-0189 §2 puts the
    ``content``/``warrant`` tie on the producer and adds no validator, so a warrantless
    resolved retirement is constructable and no producer in the tree builds one. It is
    not rendered as *no longer held* — that would be false, the content is right there —
    and it asserts no band, no origin and no source, which is the only honest answer
    available.

    Args:
        warrant: The retired record's warrant, or ``None``.

    Returns:
        The lead that introduces the content, and the note that follows it.
    """
    if warrant is None:
        return (
            "[dim]origin unrecorded —[/]",
            "I cannot say how this was held or what reported it.",
        )
    match warrant.band:
        case BeliefBand.ATTESTED:
            lead = "[yellow]someone else's words —[/]"
            note = (
                (
                    f"{_safe(warrant.attestation.reported_by)} reported this, and said it "
                    f"was current as of {_when(warrant.attestation.reported_at)}, on that "
                    f"source's own clock. These are not my words and not yours."
                )
                if warrant.attestation is not None
                else "A connected source reported this. These are not my words and not yours."
            )
        case BeliefBand.ASSERTED:
            lead = "[dim]your own words —[/]"
            note = "You told me this; it is neither a source's report nor my inference."
        case BeliefBand.DERIVED:
            lead = "[dim]my own inference —[/]"
            note = "I worked this out, so these are my words rather than a source's."
            if warrant.rests_on_recorded_external_content:
                note += (
                    " Some of what I worked it out from came from a connected source "
                    "rather than from you."
                )
        case _:  # pragma: no cover - exhaustive
            assert_never(warrant.band)
    return lead, note


def _render_retirements(question: Question) -> None:
    """Render exactly what accepting a question would retire (ADR-0078 §8, ADR-0189 §4).

    A conflict that has been retired since the question was asked does not resolve
    and is rendered as **no longer held** rather than omitted: the user should be told
    that the thing they would be overruling is already gone. Omitting it would
    understate the answer's scope in one direction and overstate it in the other.

    Each resolved entry now carries where its content came from
    (:func:`_retirement_origin`), which is what closes #673. The **unresolved** entry
    deliberately gains nothing: ADR-0189 §4's last retirement clause rules that where
    the warrant is absent the surface "renders it as *no longer held* … and asserts
    nothing about its band, its origin or its source. It renders no third state as
    ``False`` and no absence as a value." There is no attested tombstone to construct —
    §2 makes ``warrant`` and ``content`` ``None`` together — so this line stays exactly
    the sentence it was.

    Every value on both arms is neutralised for this terminal (``_safe``, ADR-0042 §4,
    ADR-0189 §9's last clause but one). A ``reported_by`` is a value this system
    declared and a ``reported_at`` is an instant, but a ``content`` is neither, and the
    line that renders them together escapes all of them — so no retired content can
    forge the attribution of the span above or below it.
    """
    if not question.retires:
        console.print("  [dim]Accepting would retire:[/] nothing")
        return
    console.print("  [dim]Accepting would retire:[/]")
    for retirement in question.retires:
        if retirement.content is None:
            console.print(
                f"    - [dim]{_safe(retirement.record_id)} — no longer held, so accepting "
                f"would not touch it[/]"
            )
            continue
        lead, note = _retirement_origin(retirement.warrant)
        console.print(
            f"    - {lead} {_safe(retirement.content)} [dim]({_safe(retirement.record_id)})[/]"
        )
        console.print(f"      [dim]{note}[/]")


def _render_successor(question: Question) -> None:
    """Name the question an answer to this one already raised, with its state (§9).

    Reached where a re-deferral admitted a successor and the answer was then
    interrupted. **Rendered by the successor's own state**, because naming it without
    one would be the failure ADR-0078 §9 warns about: only a waiting successor is a
    question the user can go and answer, while a declined or interrupted one needs its
    own handling and calling either "the follow-on question" would advertise something
    they cannot act on.
    """
    successor = question.successor
    if successor is None:
        return
    identifier = _safe(successor.id)
    match successor.state:
        case QuestionState.OPEN:
            console.print(
                f"  [dim]Your answer raised a further question, which is waiting:[/] "
                f"[bold cyan]{identifier}[/]"
            )
        case QuestionState.DECLINED:
            console.print(
                f"  [dim]Your answer landed on a question you had already declined:[/] "
                f"{identifier} [dim](forget it to be asked again)[/]"
            )
        case QuestionState.INTERRUPTED:
            console.print(
                f"  [dim]Your answer landed on another interrupted answer:[/] {identifier} "
                f"[dim](dispose of that one too)[/]"
            )
        case QuestionState.APPLIED | QuestionState.STALE | QuestionState.REDEFERRED:
            console.print(
                f"  [dim]Your answer raised a further question, since settled:[/] {identifier}"
            )
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(successor.state)


def _render_answer(outcome: AnswerOutcome) -> int:
    """Render what one answer did, and map it to an exit code (ADR-0078 §8, §9).

    Five outcomes, and a **re-deferral is reported as a completed answer** carrying
    the next question rather than as a failure: the answer was used, it raised
    something new, and rendering that as "your answer went nowhere" would be the same
    lie in a smaller place.

    Two facts are reported *alongside* whichever outcome applies, never in place of
    it. A question destroyed while its answer was being applied is a true statement
    the user brought about, and what is said about the answer comes from the ingest
    the engine still held — never inferred from the failed bookkeeping. And a
    re-deferral that could queue no follow-up at all says so, because calling it
    "re-deferred" would claim a question was asked when none was.
    """
    match outcome.kind:
        case AnswerKind.APPLIED:
            console.print(
                f"[green]Applied.[/] That is what I believe now "
                f"[dim]({_safe(outcome.record_id or '')})[/]"
            )
        case AnswerKind.REJECTED:
            console.print(
                "[green]Declined.[/] Nothing was written, and I will not ask you this again "
                "— forget the question if you want to be asked."
            )
        case AnswerKind.STALE:
            console.print(
                "[yellow]Not applied.[/] What that question was about no longer applies, so "
                "accepting it would have stored a belief that was already out of date."
            )
        case AnswerKind.NOT_OPEN:
            console.print(
                "[yellow]That question is not open.[/] It may never have existed, or it may "
                "have lapsed, been answered, or have an answer already in flight — "
                "'assistant questions' lists the ones that are still open."
            )
            return _EXIT_ERROR
        case AnswerKind.REDEFERRED:
            _render_redeferral(outcome)
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(outcome.kind)
    if outcome.disposed:
        console.print(
            "[dim]Note: that question was destroyed while your answer was being applied, "
            "so no record of the answer was kept.[/]"
        )
    return _EXIT_OK


def _render_redeferral(outcome: AnswerOutcome) -> None:
    """Render an answer that was used and raised a further question (§5a, §9).

    The successor is rendered **by its state**, for :func:`_render_successor`'s reason.
    Where no successor could be queued at all — the queue was full and this admission
    had no exemption to spend — the line says exactly that rather than pointing at a
    question that does not exist.
    """
    console.print(
        "[yellow]Not applied yet.[/] Your answer was used, but it turned out to "
        "contradict something else you told me that you had not been shown."
    )
    successor = outcome.successor
    if successor is None:
        if outcome.successor_refused:
            console.print(
                "  [yellow]The question queue is full, so I could not put the follow-up to "
                "you.[/] Answer or forget some of what is waiting, then teach me the "
                "correction again."
            )
        return
    identifier = _safe(successor.id)
    match successor.state:
        case QuestionState.OPEN:
            # Named and offered are two renderings of one id, and only the second is
            # quoted: the name is read, the command is pasted.
            offer = (
                f"[dim](assistant answer {_argument(successor.id)} --accept)[/]"
                if _is_pasteable(successor.id)
                else _uncopyable(
                    "Its id", "'assistant answer' still takes it, given the exact bytes."
                )
            )
            _print_hint(f"  [dim]Here is the follow-up:[/] [bold cyan]{identifier}[/] {offer}")
        case QuestionState.DECLINED:
            console.print(
                f"  [dim]That raises a question you had already declined:[/] {identifier} "
                f"[dim](forget it to be asked again)[/]"
            )
        case QuestionState.INTERRUPTED:
            console.print(
                f"  [dim]That raises a question whose own answer was interrupted:[/] "
                f"{identifier} [dim](dispose of that one first)[/]"
            )
        case QuestionState.APPLIED | QuestionState.STALE | QuestionState.REDEFERRED:
            console.print(f"  [dim]That raises a question already settled:[/] {identifier}")
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(successor.state)


def _when(instant: datetime) -> str:
    """Render an instant the engine supplied, in UTC.

    Pure formatting of a value that arrived on the DTO — no clock is read here, and
    none may be (golden rule 3): every time this surface shows is one memory
    recorded, never one this process observed.
    """
    return instant.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _decided_at(instant: datetime) -> str:
    """:func:`_when` at the precision a **record** owes (ADR-0186 §7).

    Every other instant on this surface is context for a value the user is reading
    now — when a belief was last revised, when a question stops being answerable —
    and a minute is the right grain for those. A recorded ruling's instant is a
    different kind of fact: §7 requires "the instant it was decided" rendered as part
    of the row, and §7's last-but-one clause forbids a surface omitting, truncating
    or summarising "any part of what it renders".

    **Minute precision is a truncation, and it collapses exactly the rows a reader
    most needs told apart.** A ``CONFIRM`` and the ``ALLOW`` that answers it are
    typically seconds apart, so at ``%H:%M`` the pair renders as one instant twice —
    a history that is internally consistent and chronologically false, which is the
    reading ADR-0021 §4 wrote its ordering rule against. ADR-0186 §2's order is by
    ``decided_at`` descending with an ``id`` tie-break, and a rendering that cannot
    show why two adjacent rows are in the order they are in has hidden the ordering
    key.

    **Always six fractional digits, never "only when interesting."** A stable width
    keeps a column readable and keeps the value comparable between two rows; a
    fraction shown only when non-zero is the shape ADR-0181 §6 argues against for a
    different fact — a reader learns to treat its presence as significant and its
    absence as sameness. ``datetime`` resolves to the microsecond, so this is the
    whole of the value.

    A pure formatting of a value that arrived on the record — no clock is read here,
    and none may be (golden rule 3).
    """
    return instant.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f UTC")


def _elision_ceiling(elided: int) -> str:
    """The ceiling ADR-0107 §5 owes beside a rendered citation count, or nothing.

    Empty where nothing was displaced, which is every belief in a deployment that
    has never hit ADR-0086 §1's bound — so this adds a clause exactly when there is
    a fact to add and is silent otherwise.

    **The shape is ADR-0086 §4's, and both halves of it are obligatory.** The count
    is an *upper bound* over the record's whole history and not a total, so it is
    rendered as "up to" and never as a figure to be added to the one beside it. And
    an elision is **not a tombstone**: the episode may be perfectly intact, and the
    line says the reference was dropped rather than that the data was lost. Getting
    that half wrong tells a user their data is gone when it is not — the failure
    ADR-0091 §1's second clause exists to prevent, and the reason
    :func:`_render_evidence` must never grow an entry for this.
    """
    if elided <= 0:
        return ""
    return (
        f" Up to {elided} more piece(s) stood behind it that I no longer keep a "
        "reference to — those may still exist; I stopped carrying them, they were "
        "not lost."
    )


def _outside_warrant(belief: Belief | BeliefSummary) -> str:
    """That a **derived** row's origin came from outside, or nothing (ADR-0189 §4).

    §4's third clause: a surface conveys that a warrant came from outside where the
    band is ``DERIVED`` and the externality answer is ``True``, read from
    ``rests_on_recorded_external_content`` beside ``band``. This is the sentence that
    discharges it, and its two silences are as ruled as its text.

    **Two arms, because the clause reaches a record whose warrant is not a
    derivation** (ADR-0223 §5). A captured episode is projected into this listing
    like anything else — ``assistant beliefs --kind episodic`` is documented as the
    way to see captured turns — and ADR-0223 §1 stamps
    ``Provenance.derived_from_external`` on one, so the predicate is now ``True`` of
    a record the belief sentence is false of in every clause: this system did not
    work an episode out, there is nothing it worked it out *from* (ADR-0074 §4 makes
    ``evidence`` empty by decision), and an episode's warrant is that it happened,
    which is entirely this system's own. §5 rules the fix as a **distinct arm**
    rather than a suppression: the clause is not narrowed, the projections stay
    kind-blind, and what changes is only the wording this surface may use.

    The episodic wording satisfies §5's three conditions. It does not attribute the
    episode's content, or any part of it, to a source outside this system; it does
    not state that the episode was worked out from an external report; and it does
    state the fact the mark actually records — that the exchange this record renders
    was conducted over material that included a record resting on recorded external
    content. It says *traces back to* rather than *came from* because the mark is a
    disjunction over :func:`~ai_assistant.core.types.rests_on_recorded_external_content`
    and not over the band: the material may be this system's own derived sentence
    whose warrant reaches a source, and a phrase claiming the words themselves were a
    source's would overclaim on exactly the second-order case ADR-0223 §10's second
    test exists for.

    **The arm reaches this renderer and not the question or retirement ones**, and
    that is scope rather than oversight. §5 binds "every surface that renders the
    belief listing"; a :class:`~ai_assistant.core.types.Question` renders a *proposal*
    (:func:`_proposal_origin`) and no proposal is ever episodic — an observer "distils
    evidence, it does not manufacture it" (ADR-0077 §2) — and no episode reaches a
    deferral at all, because capture writes through ``write_atomic`` and never through
    ``MemoryWriter.ingest``, so ADR-0106 §6's gate is not on its path (ADR-0223 §8).
    A lane that ever routes capture through the writer inherits this arm's question
    with the rest of that section's obligations.

    **Everything else in the row is untouched**, which is the byte-identity §10's
    eighth test asks for: an unstamped episode renders what it rendered before, the
    head sentence :func:`_why_derived` computes is not rewritten for either kind, and
    a kind this enum gains later takes the belief arm rather than a fifth state
    nobody wrote (the derivation :data:`_DEFAULT_BELIEF_KINDS` makes one seam over).

    **It says nothing about the record's own content, and that prohibition is the
    clause itself.** §4 is explicit that a surface "does **not** present the record's
    own content as third-party text on that ground: the content is a sentence this
    system's model wrote, and ADR-0098 §1 decides externality by the recorded origin
    of the text." ADR-0098 §7's own round-6 mistake was exactly this reach, so each
    arm names the origin of the *occasion* or the *warrant* and affirms the words are
    mine in the same breath.

    **And it is silent on ``False`` rather than negative, on both arms.** A ``False``
    is *nothing external is recorded in this warrant*, never *nothing external
    influenced it* (ADR-0098 §5, ADR-0106 §1, ADR-0223 §5's last clause): the link is
    unrecoverable once a model's output is recorded truthfully, so a surface printing
    "nothing outside reached this" would assert what no field on the record holds.
    The silence is taken **before** the kind is looked at, so neither arm can render a
    ``False`` as an assurance and a third arm could not either.

    Args:
        belief: The projected row being explained. Both of its fields are read as the
            engine computed them — the predicate is never recomputed here from
            ``band``, which ADR-0189 §2 forbids and which would drop the disjunction's
            second half anyway, and ``kind`` is the projection's own tag rather than
            anything inferred from the content.

    Returns:
        The clause, or the empty string where there is nothing that can honestly be
        said.
    """
    if not belief.rests_on_recorded_external_content:
        return ""
    if belief.kind is MemoryKind.EPISODIC:
        return (
            " Some of the material I had in front of me during this exchange traces "
            "back to a connected source rather than to you — the record above is "
            "still my own account of what was said."
        )
    return (
        " Some of what I worked it out from came from a connected source rather than "
        "from you — the belief above is still my own sentence, but its warrant is not "
        "entirely mine."
    )


def _why_derived(belief: Belief | BeliefSummary) -> str:
    """Why a **derived** belief is held: the count, what is gone, the ceiling, the origin.

    Split out of :func:`_why` so the ceiling is appended **once, on every path**
    rather than per branch. That is the structural point: ADR-0107 §5 owes the
    ceiling wherever this surface renders a citation count, and this branch renders
    one in all four of its states — including the state that renders it as *none*.
    A per-branch append would let a fifth state be added later with the clause
    forgotten, and the belief that elided nine hundred citations is exactly the one
    that would go unmentioned.

    **ADR-0189 §4's outside-warrant clause rides on the same argument and the same
    append** (:func:`_outside_warrant`). §4 binds it to the band rather than to any
    of the four count states, so a per-branch append would be four chances to forget
    it — and the belief whose warrant came from a connected source is exactly the one
    a user needs told about, on every one of them.

    **Two of the four states say something that stops being true once anything has
    been displaced, and both are repaired here rather than qualified.**

    * "no supporting evidence was recorded" claims nothing was ever there. For a
      belief whose history displaced citations that is false — evidence *was*
      recorded and the reference to it was dropped — and it is the statement
      ADR-0107 §7 prohibits on every band.
    * "nothing supports it any more" is the sentence ADR-0107 §7 names by name.
      Every citation the belief still carries has gone, which the line keeps
      saying; but the elided episodes may be intact and still supporting it, so
      the flat claim is false in the direction ADR-0073 §4 forgives least. The
      ceiling replaces it with what can honestly be said — that more stood behind
      it and this surface cannot report their fate.

    **The predicate itself is untouched** (ADR-0107 §7): ``unsupported`` keeps
    ADR-0085 §4a's one definition on both types. Adding ``and evidence_elided == 0``
    to it would answer "does anything support this" with a confident ``False``,
    which is no better founded than the confident ``True`` — nothing on the record
    says whether an elided citation still resolves. "We cannot say" is expressible
    in a sentence and not in a boolean, so the repair is here.
    """
    ceiling = _elision_ceiling(belief.evidence_elided)
    if belief.evidence_count == 0:
        head = (
            "I worked it out, and I carry no evidence for it now."
            if ceiling
            else "I worked it out, and no supporting evidence was recorded."
        )
    elif belief.unsupported:
        head = (
            f"I worked it out from {belief.evidence_count} piece(s) of evidence, "
            "none of which still exists. I still hold it — I have not unlearnt it "
            "because the evidence went"
        ) + ("." if ceiling else " — but nothing supports it any more.")
    elif belief.lost_evidence:
        head = (
            f"I worked it out from {belief.evidence_count} piece(s) of evidence, "
            f"{belief.lost_evidence} of which no longer exists. The confidence "
            "below reflects what is left."
        )
    else:
        head = f"I worked it out from {belief.evidence_count} piece(s) of evidence."
    return head + ceiling + _outside_warrant(belief)


def _why_episodic(belief: Belief | BeliefSummary) -> str:
    """Why a captured **episode** is held: because it happened (#1891, ADR-0075 §2).

    An episode reaches this listing through the documented ``assistant beliefs --kind
    episodic``, and its provenance is ``OBSERVED``, so ``band_of`` files it in the
    ``DERIVED`` band and it used to be explained by :func:`_why_derived`: *"I worked it
    out, and no supporting evidence was recorded."* Every clause of that is false of a
    recorded turn. Nothing worked it out; there is nothing it was worked out *from*,
    because ADR-0074 §4 leaves an episode's ``evidence`` empty **by decision** rather
    than by accident; and "no supporting evidence was recorded" reads as a deficiency
    where there is none to report. ADR-0075 §2 is the doctrine the old line
    contradicts: recording that an exchange happened "is true because it happened, a
    policy has nothing to weigh".

    **The header above the line is deliberately not changed, and that is this lane's
    answer to #1891's open display question.** ADR-0073 §4 requires *every* row to
    convey its band — "never omitted, never implied by position alone" — and its
    confidence, with no exemption for a kind; ADR-0072 §6 says the same of anything
    rendered as a belief. The sibling page goes further: its rows are what the user's
    own band checkboxes selected, so a row that stopped naming its band would stop
    saying which box it arrived under. So the band and the confidence stay, and this
    line says what they are — a filing, and a standing figure (ADR-0074 §4 sets it at
    capture and documents it as "standing rather than certainty") — rather than
    letting the row imply that the system is 90% sure the conversation took place.

    **The externality sentence is appended here exactly as it is appended to a
    belief**, through the same :func:`_outside_warrant`, so ADR-0223 §5's arm survives
    this rewording unaltered: its first clause is that the fact is never omitted for an
    episode, its second fixes the wording, and neither is touched by giving the head
    sentence in front of it an honest voice. Appended once, at the single exit, for the
    reason :func:`_why_derived` appends it once — a second exit is a second chance to
    forget it.

    **And it is reached only from the ``DERIVED`` band**, which keeps ADR-0189 §4's
    clause exactly where that ADR put it: the externality sentence is owed "where the
    projected record's band is ``DERIVED``", so routing on the kind *inside* the band
    match cannot render it on a band the clause does not reach. No episode is written
    into another band today — capture stamps ``OBSERVED`` — and if one ever were, the
    band's own sentence is what it would get, which is the same conservative direction
    :func:`_why` takes everywhere else.

    Args:
        belief: The projected row being explained.

    Returns:
        The reason, with ADR-0223 §5's clause where the mark is set.
    """
    return (
        "this records an exchange that happened — I captured it at the time, so "
        "there was nothing to work out and nothing to weigh. The line above files it "
        "among my beliefs because that is where a captured turn sits, and the "
        "confidence there is a standing figure rather than a measure of doubt that "
        "it happened."
    ) + _outside_warrant(belief)


def _why(belief: Belief | BeliefSummary) -> str:
    """Why this belief is held — band-dependent (ADR-0073 §4).

    Total over :class:`~ai_assistant.core.types.BeliefBand` and mechanically so: the
    wildcard does nothing but ``assert_never``, so a band added to ``core`` without a
    line here fails the gate rather than rendering an empty reason. The same shape
    ``band_of`` itself uses.

    The answer is complete for one band and owed for two, and the wording keeps
    ADR-0073 §4's two floors:

    * **Derived** — :func:`_why_derived`, which counts the citations, counts the
      ones that no longer resolve **separately and out loud** (ADR-0077 §6), and
      states the elision ceiling ADR-0107 §5 owes beside any rendered count. They
      are never rendered as ids; the ids are not even carried to this module
      (:class:`~ai_assistant.orchestration.Belief` holds resolved content or a
      tombstone), so no renderer here can pass one off as the warrant. A belief whose
      support is *entirely* gone says so, and says that it is still held — because it
      is not retired, and a line implying otherwise would misdescribe what the user
      can still do with it.
    * **Derived, and a captured episode** — :func:`_why_episodic`, because an
      episode is not a derivation and the derived line is false of it in every clause
      (#1891, ADR-0075 §2). The kind is asked **inside** the band's arm rather than
      before the match, so ADR-0189 §4's externality clause stays bound to the
      ``DERIVED`` band where that ADR put it.
    * **Attested** — the reporting source is **named**, the instant that source said
      the fact was current is stated on *its* clock, and the line still says outright
      that ``Last revised`` is the assistant's clock rather than the source's
      (ADR-0189 §4, ADR-0073 §4).

    **The asserted and attested lines are unchanged by ADR-0107, and that is its §2
    applied rather than an omission.** §2 scopes the elision disclosure to
    ``DERIVED`` because that is the band ADR-0073 §4 put the citation-count floor
    in: an assertion's warrant is the user's own word and an attestation's is the
    source's report, so neither line renders a citation count and neither owes a
    ceiling beside one (ADR-0107 §5 requires nothing of a surface that renders no
    count). Both still carry the number on their DTO (§3) — the silence is about
    rendering, and only about rendering. Whether either band's line *should* render
    a count at all is ADR-0073 §4's own ``ATTESTED`` gate, left to the lane holding
    leg 6's first ``EXTERNAL`` producer (ADR-0107 §10).

    **This line used to state a limit of the surface, and ADR-0189 removed the
    limit** (**#1276**). Which source spoke, and when, were always *held* — a
    :class:`~ai_assistant.core.types.Provenance` makes an
    :class:`~ai_assistant.core.types.Attestation` mandatory exactly on this band
    (ADR-0092 §1) — and what dropped them was the projection: neither
    :class:`~ai_assistant.core.types.Belief` nor
    :class:`~ai_assistant.core.types.BeliefSummary` had anywhere to put one. ADR-0189
    §2 gave both of them one, so this branch now names the source and states the
    instant instead of explaining that it cannot, which is ADR-0098 §8's second tier
    reached and ADR-0073 §4's ``ATTESTED`` gate met at the surface.

    **Two floors survive the change and one of them is new.** ``Last revised`` is
    still declared to be this system's clock, because ADR-0073 §4 forbids offering it
    as the source's and the new line puts a *second* instant on the screen beside it —
    which is precisely the error ADR-0189's Consequences names as newly available to a
    surface that renders one of the two facts. And the source is named at **source
    granularity and no finer** (ADR-0189 §4, ADR-0098 §8's third clause): the value is
    apposed to "a connected source" so it cannot be read as a person, because
    ADR-0093 §7 forbids deriving a reader's identity from what the source contains, so
    the organiser of an invite and the sender of a mail are not on the record and
    cannot be.

    **Where no label is configured the identity is what renders**, which is ADR-0093
    §7's own fallback adopted unchanged by ADR-0189 §5 — and no label is configured
    anywhere yet, because ADR-0189 §8 leaves the mechanism to the registry lane.

    **The attestation-less attested belief is off-contract and still gets a sentence.**
    ADR-0189 §2 adds no cross-field validator to these two DTOs, deliberately, so the
    type admits a state the store cannot produce. Rendering the old "I recorded which
    source" line there would claim something this projection does not show; claiming
    nothing was recorded would err in the direction ADR-0073 §4 forgives least. What is
    true either way is that what reached *this surface* does not carry it, so that is
    what it says.
    """
    match belief.band:
        case BeliefBand.ASSERTED:
            return "you told me, and your own word is the whole of it."
        case BeliefBand.DERIVED:
            if belief.kind is MemoryKind.EPISODIC:
                return _why_episodic(belief)
            return _why_derived(belief)
        case BeliefBand.ATTESTED:
            if belief.attestation is None:
                return (
                    "a source you connected reported it — neither your word nor my "
                    "inference. What reached me here does not name that source or say "
                    "when it spoke, so 'Last revised' below is when I changed my mind "
                    "and not when the source spoke."
                )
            return (
                f"a connected source reported it — {_safe(belief.attestation.reported_by)}, "
                f"neither your word nor my inference. That source said this was current "
                f"as of {_when(belief.attestation.reported_at)}, on its own clock; "
                f"'Last revised' below is when I changed my mind and not when the "
                f"source spoke."
            )
        case _:  # pragma: no cover - exhaustive
            assert_never(belief.band)


def _forget_warning(band: BeliefBand) -> str:
    """What forgetting a belief in this band costs (ADR-0073 §5).

    The ceremony is uniform in mechanism and asymmetric in message, because the
    consequence is: an assertion is not re-derivable and losing one is unrecoverable
    (ADR-0072 §1, ADR-0038 §2), while a derived or attested belief loses the belief
    and not its origin. The obligation is to represent a deletion as neither more
    final than it is nor less. Total over the bands, like :func:`_why`.
    """
    match band:
        case BeliefBand.ASSERTED:
            return "You told me this. Forgetting it is permanent — nothing can work it out again."
        case BeliefBand.DERIVED:
            return (
                "I worked this out. Forgetting it destroys the belief but not what I "
                "worked it out from, so I may reach it again."
            )
        case BeliefBand.ATTESTED:
            return (
                "A connected source reported this. Forgetting it destroys my copy but "
                "not the source, so a later sync may bring it back."
            )
        case _:  # pragma: no cover - exhaustive
            assert_never(band)


def _render_content(content: str) -> None:
    r"""Print a row's canonical content, its own line breaks intact (#1890, ADR-0042 §4).

    **A captured episode is the first listed record whose content is legitimately more
    than one line.** ``_exchange_of`` writes it as "The user asked: …" and "The
    assistant's plan: …" separated by a ``\n``, and this row rendered that break as
    ``�`` — because :func:`_safe` replaces ``\n`` by default, which is #1336's fix
    reaching a value it was never aimed at.

    **The default is right, and the reason it is right is exactly what this renderer
    has to answer for.** A value interpolated into a line the CLI authored — ``Why:``,
    ``id:``, a numbered step — can, with one newline, forge a *second* line
    indistinguishable from one this adapter wrote, which is ADR-0042 §4's threat
    arriving without a single control character. Eating the newline is what stops it,
    and a renderer that simply stopped eating it here would open that hole on **every**
    row: :data:`~ai_assistant.core.types.EncodableText` requires only that a value be
    writable, so ``fact\nWhy: you told me this\nid: rec-9`` is a content any kind may
    carry, and printed as three plain indented lines it is three fields of this row.
    Adversarial review, round 1, ``blocker``.

    **So the break is kept and the forgery is closed by a marker instead.** Where the
    content is more than one line, *every* line of it is printed behind a gutter no
    line this adapter writes ever carries — the row's own fields lead with their label,
    a citation with ``-`` or a tombstone, and none of them with ``│``. A forged
    ``Why:`` therefore arrives as ``│ Why:`` and reads as what it is: part of the
    record's text. The marker is on every line rather than on the continuations alone
    so that the block is legible as one quoted thing, and because a first line without
    it would be one line of an unmarked block for the eye to anchor on.

    **"Every line" means every line on the screen, so the wrapping is taken here rather
    than left to the console.** Rich does not repeat a literal prefix on the
    continuations it wraps: handed one long line, it emits the gutter once and puts the
    remainder at the margin, so ``…many words… Why: forged`` becomes a second display
    line the marker never reached. Adversarial review, round 2, ``blocker``. The
    content is therefore wrapped to the room left beside the gutter — by Rich's own
    measurement, which counts cells rather than characters — and the gutter is written
    onto each piece. What is printed is a :class:`~rich.text.Text` rather than a markup
    string, so the escaping :func:`_safe_prose` applied is resolved once, by
    :meth:`~rich.text.Text.from_markup`, and cannot be re-parsed by the print.

    **A single-line content is printed exactly as it was**, which is not merely tidy:
    one line cannot forge a second, so the marker would be ceremony bought with a
    change to every row this system has ever rendered. Only a value carrying the break
    that creates the risk pays for it.

    **Scoped by shape rather than by kind.** Keeping the break only for
    ``EPISODIC`` — the narrower repair — would leave the hole precisely where the
    newlines actually are, since an episode's content quotes the user's own message and
    a user may type a newline; and it would render a ``�`` for any other kind that
    ever legitimately holds one. What decides the rendering is what the value *is*, and
    the safety no longer depends on that decision being right.

    Rich markup is escaped over the **whole** value before it is split, never per line,
    for the reason :func:`_safe_prose` records: Rich's tag pattern matches across a
    newline, so ``[red\nbold]`` survives per-line escaping intact and is then consumed
    as markup. Splitting *after* the escape cannot resurrect it, and the gutter is the
    adapter's own markup, outside the escaped text.

    Args:
        content: The record's canonical text, as the engine carries it.
    """
    lines = _safe_prose(content).split("\n")
    if len(lines) == 1:
        console.print(f"  {lines[0]}")
        return
    gutter = Text("  │ ", style="dim")
    room = max(console.width - len(gutter), 1)
    for text_line in lines:
        for wrapped in Text.from_markup(text_line).wrap(console, room):
            console.print(gutter + wrapped)


def _render_belief_summary(summary: BeliefSummary) -> None:
    """Render one row of the **listing** (ADR-0077 §6, ADR-0085 §4a).

    The listing "resolves *existence* and renders the count, the lost count, and the
    adjusted confidence"; the citations themselves belong to the single-belief view.
    The split used to be a ``evidence=False`` argument this module chose to pass —
    now it is the *type*: a :class:`~ai_assistant.core.types.BeliefSummary` carries
    no citations, so this renderer could not print one if it tried, and the engine
    could not have shipped one for it to print.
    """
    _render_belief_fields(summary)


def _render_belief(belief: Belief) -> None:
    """Render the **single-belief** view: the same fields, plus the warrant.

    Printing every citation for a fifty-belief page would bury the listing it is
    part of; printing none of them where the user is about to destroy the belief
    would hide the warrant they are judging.
    """
    _render_belief_fields(belief)
    _render_evidence(belief)


def _render_belief_fields(belief: Belief | BeliefSummary) -> None:
    """Render what ADR-0073 §4 requires **both** views to convey.

    The band leads the row and is never left to be implied by position; confidence,
    kind, the canonical content, why it is held, when the assistant last revised it
    and the id are all shown, as is the end of its validity window where one is set.
    Every listed belief is live, so an *open* window carries no information and is
    not rendered as though it did.

    **The confidence shown is the presented one**, already lowered for support that
    has gone (ADR-0077 §6). This module does not compute it and could not: the stored
    number is not carried here at all, which is what stops two surfaces quoting
    different figures for one belief.

    The ``Why`` line reads only the counts and the kind, which both types carry —
    which is why the two views share this renderer rather than one of them needing
    its own.

    **The content is printed as a block whose every line carries the row's indent**
    (:func:`_render_content`), because an episode's content is legitimately two lines
    and this row used to render the break between them as ``\ufffd`` (#1890).

    Engine-supplied text — the content and the id — is neutralised for this
    terminal like any other (``_safe``, ADR-0042 §4). The band and kind are this
    system's own closed vocabularies, not carried data.
    """
    console.print(
        f"\n  [bold cyan]{belief.band.value}[/] · {belief.kind.value} · "
        f"confidence {belief.confidence:.2f}"
    )
    _render_content(belief.content)
    console.print(f"  [dim]Why:[/] {_why(belief)}")
    console.print(f"  [dim]Last revised:[/] {_when(belief.last_updated)}")
    if belief.valid_until is not None:
        console.print(f"  [dim]Believed until:[/] {_when(belief.valid_until)}")
    console.print(f"  [dim]id:[/] {_safe(belief.id)}")


def _render_evidence(belief: Belief) -> None:
    """Render the citations behind one belief, tombstoning what is gone (ADR-0077 §6).

    A citation that no longer resolves is **an explicit tombstone** — never a bare id,
    never a silent gap (ADR-0073 §4's floor). The tombstone says an evidence item
    stood here and is gone, and deliberately does not say what it was; it also does
    not distinguish *deleted* from *expired*, because the read cannot tell them apart
    and the user's question — "is there still something behind this?" — is answered
    by absence either way.
    """
    if not belief.evidence:
        return
    console.print("  [dim]Because:[/]")
    for item in belief.evidence:
        if item.content is None:
            console.print("    [yellow]—[/] [dim]an item of evidence stood here and is gone.[/]")
        else:
            console.print(f"    - {_safe(item.content)}")


def _render_beliefs(page: tuple[BeliefSummary, ...], *, limit: int, offset: int) -> None:
    """Render one page of beliefs (ADR-0073 §7).

    **No total is shown**, and none is available to show: "is there more" is answered
    by asking for the next page, so a full page says so and names the offset that
    would fetch it, rather than implying a count nobody computed.
    """
    if not page:
        console.print("[dim]No live belief matches.[/]")
        return
    console.print(f"[bold]{len(page)} belief(s)[/], most recently revised first.")
    for summary in page:
        _render_belief_summary(summary)
    if limit and len(page) == limit:
        console.print(
            f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
        )


def _render_forget_prompt(belief: Belief) -> None:
    """Show what is about to be destroyed, and what destroying it costs (ADR-0073 §5).

    Three things, in this order, because a person cannot consent to destroying
    something they were not shown (ADR-0042 §4, ADR-0052 §4):

    1. the belief itself, in full;
    2. the band-appropriate warning — what is lost, and what is not;
    3. what the confirmation actually covers. It is consent to forget **the belief
       that id names**, not a guarantee that what is destroyed is byte-for-byte what
       was just rendered: the show and the delete are two calls and the window
       between them is named rather than closed (ADR-0073 §5). And it destroys rather
       than retires, which is the contrast — kept versus destroyed — that a surface
       offering both a correction and a deletion owes (ADR-0073 §6).
    """
    console.print("\n[bold yellow]About to forget this belief[/]")
    _render_belief(belief)
    console.print(f"\n  [yellow]{_forget_warning(belief.band)}[/]")
    console.print(
        "  This destroys the record: nothing of it is kept, not even in an export. "
        "To fix it instead, use [bold]assistant learn --kind correction[/], which "
        "retires the old belief and keeps it on the record."
    )
    console.print(
        "  [dim]You are forgetting whatever belief that id names when you answer, "
        "which may have changed since it was shown.[/]"
    )


def _render_no_such_belief(belief_id: str) -> None:
    """Report an id that names no *live* belief (ADR-0073 §5).

    The read behind this surface is live-only, so an id naming a belief the assistant
    has since revised does not resolve and is declined rather than destroyed —
    deleting what cannot be displayed is exactly what the ceremony forbids. The right
    to erase such a record is not lost; what is missing is a surface for it, which
    belongs with the deferred history view (ADR-0073 §3, §10).
    """
    console.print(
        f"[yellow]No live belief has the id[/] {_safe(belief_id)}. "
        "It may never have existed, or it may have been revised or forgotten already — "
        "this surface shows and destroys only beliefs held right now."
    )


def _scope_phrase(scope: Sequence[GrantScope]) -> str:
    """Say what a scope allows, in words rather than in enum values.

    Total over :class:`~ai_assistant.core.types.GrantScope` through
    :func:`assert_never`, so a further member surfaces at type-check time rather
    than as a missing phrase — the same discipline every other exhaustive
    rendering on this surface uses. ADR-0133's ``NOTIFY`` is the member it was
    written for and it did its job: the addition failed the type check instead of
    reaching a user as a silently absent clause in the confirmation they were
    shown before consenting.

    **A phrase says what the reading is used for, never what follows from it**
    (ADR-0133 §1). Granting ``NOTIFY`` decides nothing about whether the user is
    ever contacted — producing a candidate reaches nobody (ADR-0130 §1) and every
    class defaults to ``hold`` (§6) — so its phrase is about reading, on the same
    footing as ``INGEST``'s, which promises remembering rather than that any
    particular belief survives a memory policy. A phrase promising messages would
    overclaim the grant in the one place the user is deciding.
    """
    phrases = []
    for use in scope:
        match use:
            case GrantScope.FACET:
                phrases.append("looking at it while answering")
            case GrantScope.INGEST:
                phrases.append("durably remembering what it says")
            case GrantScope.NOTIFY:
                phrases.append("reading it to raise things with you unprompted")
            case _:  # pragma: no cover — exhaustive over the enum
                assert_never(use)
    return " and ".join(phrases) if phrases else "nothing"


def _render_sources(offered: tuple[GrantableSource, ...]) -> None:
    """Render the grantable sources, each with its location and its standing.

    **Liveness is read off ``live`` and never derived** (ADR-0102 §3): the hub
    computed it from the ``revokes`` relation, and a client walking
    ``recent_grants`` instead would report a withdrawn grant as live whenever a
    clock had been corrected backwards. So this renders the field it was handed.
    """
    if not offered:
        console.print(
            "[yellow]No sources are available to connect.[/] Nothing is configured "
            "for this installation to read. Configuration says *where* a source is; "
            "a grant says *whether* I may read it — and neither stands in for the "
            "other, so there is nothing to grant until one is configured."
        )
        return
    console.print(f"[bold]{len(offered)}[/] source(s) you can connect me to:\n")
    for one in offered:
        console.print(f"  [bold cyan]{_safe(one.source)}[/]")
        # The location is shown and comes to rest nowhere: it is on this response
        # and on no stored record, in no log and in no export (ADR-0097 §9a).
        where = "not configured" if one.location is None else _safe(one.location)
        console.print(f"    reads from: {where}")
        if one.live is None:
            console.print("    [dim]not granted — I read nothing from it[/]")
        else:
            console.print(
                f"    [green]granted[/] for {_scope_phrase(one.live.scope)} "
                f"(since {_when(one.live.decided_at)})"
            )
        console.print()


def _render_no_such_source(source: str, offered: tuple[GrantableSource, ...]) -> None:
    """Report a name the enumeration does not carry, and say what it does carry.

    **The remedy is the list rather than an echo**, which is ADR-0097 §9's refusal
    rule read from the client's side: a caller that sent the value still has it, and
    what it needs is the admissible set.

    It deliberately does not speculate about *why* a name is absent. Three different
    conditions produce the same answer here — no such source, a reader whose
    declared name is not in canonical form, and a configured location that cannot be
    shown (ADR-0102 §4, §6) — and only the last two are visible to an operator, in
    the hub's log. Guessing between them at a user's terminal would be inventing a
    diagnosis this process cannot make.
    """
    console.print(
        f"[yellow]I cannot offer a source called[/] {_safe(source)}[yellow].[/] "
        "You can only grant a source I can show you first, which is what keeps a "
        "typo from becoming a permission."
    )
    if offered:
        names = ", ".join(_safe(one.source) for one in offered)
        console.print(f"Available: {names}. See 'assistant sources' for the details.")
    else:
        console.print("Nothing is configured for me to read, so there is nothing to grant.")


def _render_grant_prompt(chosen: GrantableSource, scope: Sequence[GrantScope]) -> None:
    """Show the source, where it reads from, and what the grant would allow.

    **This is ADR-0102 §6's third clause discharged**, and the ordering is the whole
    of it: the location is rendered *before* consent is taken, because a grant given
    without seeing what is being connected is the uninformed grant ADR-0097 §9a
    exists to prevent. ``--yes`` supplies the answer and never removes this
    rendering, exactly as it does not on ``forget`` (ADR-0073 §5, ADR-0052 §4).

    Where the source has **no configured location**, §9a's obligation is vacuous —
    there is nothing to show — and that is said plainly rather than left blank. The
    other case, a location that cannot be written down, never reaches here: such a
    source is absent from the enumeration, and :func:`_drive_grant` refuses to send
    ``grant`` for anything the enumeration did not carry.
    """
    console.print(f"About to connect [bold cyan]{_safe(chosen.source)}[/].\n")
    if chosen.location is None:
        console.print("  [yellow]It has no configured location.[/]")
    else:
        console.print(f"  It reads from: [bold]{_safe(chosen.location)}[/]")
    console.print(f"  You would be allowing: {_scope_phrase(scope)}.")
    if chosen.live is not None:
        withdrawal = (
            f"first with 'assistant revoke {_argument(chosen.source)}'."
            if _is_pasteable(chosen.source)
            else f"first with 'assistant revoke'. {_uncopyable('Its name')}"
        )
        _print_hint(
            "\n  [yellow]It is already granted[/] for "
            f"{_scope_phrase(chosen.live.scope)}. A source has one grant at a time, "
            f"so this will be refused — withdraw the current one {withdrawal}"
        )
    console.print(
        "\n[dim]Withdrawing later stops further reads; it does not un-remember what "
        "was already read.[/]"
    )


def _confirm_grant(_source: GrantableSource) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    Defaults to **no**, like every other consent question on this surface: the
    question is about letting the assistant read a personal source, and a bare
    Enter must not be the answer that permits it (ADR-0097 §8's posture, where
    nothing mints a grant from what is merely configured).
    """
    return typer.confirm("Connect it?", default=False)


def _render_grants(recorded: tuple[SourceGrant, ...], *, limit: int) -> None:
    """Render the grant record, newest first, without claiming any of it is live.

    **A record is shown as an act and never as a standing** (ADR-0102 §3): this
    page is ordered by ``decided_at`` and ADR-0097 §4 permits a revocation
    timestamped before the grant it revokes, so a clock correction can put the two
    out of order here — which is a display oddity and never a wrong answer, as long
    as nothing on this page pretends to answer "is it granted now". That question is
    ``assistant granted``, which reads the store (ADR-0139 §3's last clause);
    ``assistant sources`` answers what *may* be granted, so it would miss a live
    grant on a source the hub holds no reader for.
    """
    if not recorded:
        console.print("[yellow]Nothing recorded.[/] You have not granted or withdrawn anything.")
        return
    console.print(f"[bold]{len(recorded)}[/] record(s), most recent decision first:\n")
    for record in recorded:
        act = "withdrew" if record.revokes is not None else "granted"
        console.print(
            f"  [bold]{_when(record.decided_at)}[/] — {act} "
            f"[bold cyan]{_safe(record.source)}[/] for {_scope_phrase(record.scope)}"
        )
        console.print(f"    [dim]{_safe(record.id)}[/]")
    if len(recorded) == limit:
        console.print(
            f"\n[dim]Showing {limit}. Ask for more with --limit; there is no total count.[/]"
        )
    console.print(
        "\n[dim]Whether a source is granted *now* is 'assistant granted' — a record "
        "here says an act happened, not that it still stands.[/]"
    )


def _render_standing(standing: tuple[SourceGrant, ...]) -> None:
    """Render what the user currently authorises, whole (ADR-0139 §3).

    **The set is presented as it arrived.** No record is omitted because no held
    reader declares its source, nothing is merged into the enumeration of grantable
    sources, and no entry is offered as something to grant — that would present the
    one answer as the other, which §1 keeps apart and §3's first clause forbids at
    the rendering.

    **Each grant renders exactly the uses it names**, and this is the half a
    well-meaning view gets wrong. Adding the members a grant leaves out — greying
    them out beside it, listing them as "not yet allowed" — presents the user's
    decision as a half-filled form, which is a nudge toward a wider grant on the one
    surface whose whole subject is what they actually decided (§3's third clause).
    The choice context is where the whole vocabulary belongs, and that is
    ``--scope``'s help.

    **Nothing here is a claim about configuration or about reads.** Whether a held
    reader currently declares one of these sources is a different question and
    ``assistant sources`` is where it is asked (§3's fourth clause, ADR-0093 §7).
    Whether a source was *actually read* is a different question again, and this
    list still answers none of it — ADR-0139 §6's clause that no client presents a
    read, a read count or a last-read instant beside a standing grant is unchanged,
    and ADR-0185 §8 restates it so this lane cannot be read as relaxing it. What
    has changed is that the question has a surface of its own: ``assistant reads``.
    So the closing sentence names it rather than saying nothing answers it, which
    ADR-0186 §10 wrote as true "until the read surface lands".

    **It is named for what it records, which is *attempts*.** The unit there is an
    attempt and not a read (ADR-0185 §1) — a refusal is a row, and on a failure
    whether anything was opened is not determinable at all — so pointing at it as
    "the record of what was read" would overclaim in the one direction ADR-0186 §8
    bars, presenting an attempt as an event.
    """
    if not standing:
        console.print(
            "[yellow]You have not granted anything.[/] I am allowed to read no "
            "source at all. 'assistant sources' lists what you could connect me to."
        )
        return
    console.print(f"[bold]{len(standing)}[/] source(s) you currently allow me to read:\n")
    for record in standing:
        console.print(f"  [bold cyan]{_safe(record.source)}[/]")
        console.print(f"    [green]allowed for[/] {_scope_phrase(record.scope)}")
        console.print(f"    [dim]granted {_when(record.decided_at)}[/]")
        withdrawal = (
            f"assistant revoke {_argument(record.source)}"
            if _is_pasteable(record.source)
            else "assistant revoke"
        )
        _print_hint(f"    [dim]withdraw with '{withdrawal}'[/]")
        console.print()
    console.print(
        "[dim]This is what you permitted, read from the record of your own "
        "decisions. It is not a list of what is configured — see 'assistant "
        "sources' — and it says nothing about what has actually been read: "
        "'assistant reads' is where attempts to read one are recorded, and how "
        "each ended.[/]"
    )


def _render_unamendable_source(source: str, offered: tuple[GrantableSource, ...]) -> None:
    """Report that an amendment cannot be offered for a source I cannot show.

    ADR-0139 §5 carries ADR-0102 §6's disclosure into the granting half of an
    amendment without exception, and §6's own words are that "a client that cannot
    show the user the location does not send ``grant``". A source absent from the
    enumeration leaves nothing to show, so the amendment fails closed here.

    **Revocation is unaffected and is said so**, because this is exactly the case
    where it matters: ADR-0102 §4 applies no admission check to ``revoke`` precisely
    so a configuration edit can never make a grant unrevokable, and a user whose
    source has stopped being offered still has their whole remedy.
    """
    console.print(
        f"[yellow]I cannot amend the grant on[/] {_safe(source)}[yellow].[/] "
        "Amending makes a new grant, and I only grant a source I can show you "
        "first — this one is not among the sources I can offer."
    )
    if offered:
        names = ", ".join(_safe(one.source) for one in offered)
        console.print(f"Available to grant: {names}. See 'assistant sources'.")
    withdrawal = (
        f"assistant revoke {_argument(source)}" if _is_pasteable(source) else "assistant revoke"
    )
    _print_hint(
        f"[dim]Withdrawing is not affected: '{withdrawal}' works whatever is "
        "configured. 'assistant granted' shows what you currently allow.[/]"
    )


def _render_amend_prompt(chosen: GrantableSource, scope: Sequence[GrantScope]) -> None:
    """Show the source, its location and the new scope, before anything is sent.

    **ADR-0139 §5 discharged, and the ordering is the whole of it.** ADR-0102 §6's
    obligation applies to every ``grant``, and the granting half of an amendment is
    a ``grant`` — same operation, same record, same store. What makes the reminder
    worth a clause is that an amendment *feels* like modifying something already
    consented to, and a client author reasoning that way skips the one step §6
    exists for. Nothing here branches on whether the new scope is narrower: that
    branch buys nothing except somewhere for the mistake to live.

    It also renders the **existing** grant exactly as it stands, without presenting
    it as incomplete (§3's third clause), so a person can see what they are
    replacing rather than what someone thought they should have asked for.
    """
    console.print(f"About to change the grant on [bold cyan]{_safe(chosen.source)}[/].\n")
    if chosen.location is None:
        console.print("  [yellow]It has no configured location.[/]")
    else:
        console.print(f"  It reads from: [bold]{_safe(chosen.location)}[/]")
    if chosen.live is None:
        console.print(
            "  [yellow]It is not granted right now.[/] I will still withdraw first, "
            "then grant — that is the only shape this act has."
        )
    else:
        console.print(f"  It is currently allowed for: {_scope_phrase(chosen.live.scope)}")
    console.print(f"  It would then be allowed for: {_scope_phrase(scope)}")
    console.print(
        "\n[dim]This is two acts: a withdrawal, then a new grant. Between them the "
        "source is allowed nothing, and I will tell you how each one went.[/]"
    )


def _confirm_amendment(_source: GrantableSource) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    Defaults to **no**, like :func:`_confirm_grant` and for its reason: the question
    ends in a grant, and a bare Enter must not be what permits one.
    """
    return typer.confirm("Change it?", default=False)


def _render_act(
    act: str,
    outcome: _ActOutcome,
    *,
    detail: Sequence[str] = (),
    withdrew: bool | None = None,
) -> None:
    """Say what one act of the amendment did, as one of exactly three things.

    **"Not merely failed" is the whole of ADR-0139 §4's second clause**, and the
    wrong report is the one an implementer writes: catch, print the exception, exit
    non-zero. A user reads that as the amendment not having happened, goes away, and
    their source stops being read — silently, because the hub's refusal is a log
    line and a missing facet is indistinguishable from every other absence. The
    state is recoverable in one command; being told about it is what makes it so.

    Each phrasing is about **this act** and never about the source. A withdrawal
    that landed is not a statement that the source is ungranted, and a grant that
    was refused is not one either (§4's third clause) — that is
    :func:`_render_state`'s job, from a read.
    """
    match outcome:
        case _ActOutcome.LANDED:
            found = ""
            if withdrew is False:
                found = " (there was no live grant for it to withdraw)"
            console.print(f"[green]The {act} landed.[/]{found}")
        case _ActOutcome.NOT_LANDED:
            console.print(
                f"[red]The {act} is known not to have landed[/] — I was refused, so "
                f"nothing was written: {_safe('; '.join(detail))}"
            )
        case _ActOutcome.UNKNOWN:
            because = f" {_safe('; '.join(detail))}" if detail else ""
            console.print(
                f"[yellow]The outcome of the {act} is not known.[/]{because} I did "
                "not get an answer back, and it may have been done anyway."
            )
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(outcome)


def _render_amendment_stopped(outcome: _ActOutcome) -> None:
    """Say that no grant was sent after a withdrawal that did not plainly land.

    ADR-0139 §4's fourth clause for the unknown branch, and the same conservatism
    for the refused one. Sending the grant anyway would invite reasoning backwards
    from its result — refused means the withdrawal did not land, accepted means it
    did — which is precisely the inference §4's third clause forbids, because a
    refusal is equally consistent with another client having granted in between.
    """
    if outcome is _ActOutcome.UNKNOWN:
        console.print(
            "[yellow]I sent no new grant.[/] I could not tell whether the withdrawal "
            "happened, and sending a second act to find out would only give me an "
            "answer I could not read. The amendment is incomplete."
        )
        return
    console.print("[yellow]I sent no new grant.[/] The amendment is incomplete.")


def _render_unread(source: str) -> None:
    """Say the source's state is unread, and start no call to find out.

    **ADR-0139 §4's fifth clause, and its middle sentence is the load-bearing one.**
    A cancelled surface is still asked to report, which invites reaching for the
    state before reporting it — the same breach by a kinder route. ADR-0060 permits
    deferring a cancellation only while a method makes its resources safe, and a
    read performed to present a state is not that. So this says what happened to the
    act, says the source's state is unread, starts nothing, and lets the
    ``CancelledError`` leave.
    """
    console.print(
        f"[dim]I have not read what {_safe(source)} is allowed for, so I am not "
        "saying. 'assistant granted' will tell you.[/]"
    )


def _render_state(source: str, state: SourceGrant | None | _Unread) -> None:
    """State the source's current grant, from a read and never from an act's outcome.

    ADR-0139 §4's third clause is sharper than it first looks, and an earlier draft
    of that ADR got it wrong: a ``grant`` refused with ``InvalidGrantError`` is
    refused *because another client's grant is live* (ADR-0102 §5), so "the source
    is now ungranted" is false in the one case that produced the refusal. An act's
    outcome is a fact about that act; the source's state is a fact about the store;
    and one is never read off the other.
    """
    if isinstance(state, _Unread):
        console.print(
            f"[dim]I could not read what {_safe(source)} is allowed for, so I am not "
            "saying. Try 'assistant granted'.[/]"
        )
        return
    if state is None:
        console.print(f"I read [bold]{_safe(source)}[/]'s state: nothing is granted on it.")
        return
    console.print(
        f"I read [bold]{_safe(source)}[/]'s state: it is allowed {_scope_phrase(state.scope)}."
    )


def _condition_phrase(condition: NotificationCondition) -> str:
    """Say what one condition of a ruling means, in words rather than in enum values.

    Total over :class:`~ai_assistant.core.types.NotificationCondition` through
    :func:`assert_never`, the discipline :func:`_scope_phrase` uses: a ninth
    condition surfaces at type-check time rather than as a ruling rendered with a
    missing explanation.

    **Each member is worded in the one polarity it is ever shown in**, which the
    vocabulary makes safe: the four members of ``DROP_CONDITIONS`` and the four of
    ``INTERRUPT_CONDITIONS`` are disjoint groups (ADR-0130 §5), and this surface
    renders a member of the first as a ``DROP``'s reason and a member of the second
    only from a ``HOLD``'s failed set — where every entry is a condition that did
    **not** hold. So no phrase has to read both ways.
    """
    match condition:
        case NotificationCondition.EXPIRED:
            phrase = "it had already perished by the time I ruled on it"
        case NotificationCondition.REACH_OFF:
            phrase = "you have set that class to never tell you"
        case NotificationCondition.DUPLICATE:
            phrase = "I am already holding the same thing"
        case NotificationCondition.AT_CAP:
            phrase = "I am holding as many notifications as I may"
        case NotificationCondition.PERISHABLE:
            phrase = "it names no moment it stops mattering, so nothing makes it urgent"
        case NotificationCondition.REACH_INTERRUPT:
            phrase = "that class is not set to interrupt you"
        case NotificationCondition.QUIET_WINDOW:
            phrase = "it fell inside your quiet hours"
        case NotificationCondition.BUDGET:
            phrase = "your interruption budget for that window was already used up"
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(condition)
    return phrase


def _reach_phrase(reach: NotificationReach) -> str:
    """Say what one reach level does, in words. Total, for :func:`_condition_phrase`'s reason."""
    match reach:
        case NotificationReach.OFF:
            return "never tell you, and rule out what is already held"
        case NotificationReach.HOLD:
            return "keep it for when you next look"
        case NotificationReach.INTERRUPT:
            return "may reach you at the time"
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(reach)


def _hours(duration: timedelta) -> str:
    """Render a rolling window in the unit ``assistant tune --budget-window`` takes."""
    count = duration / timedelta(hours=1)
    return f"{count:g} hour" if count == 1 else f"{count:g} hours"


def _render_notifications(
    page: tuple[HeldNotification, ...], *, now: datetime, limit: int, offset: int
) -> None:
    """Render one page of held notifications (ADR-0130 §7).

    **No total is shown** and none is available: "is there more" is answered by asking
    for the next page, exactly as the belief, conversation and question listings
    answer it.

    An empty *first* page is where the arming chain is worth naming, because that is
    what an operator sees when one of its three links is missing and it is the one
    moment they are certainly looking (#979, #981).

    ``now`` is supplied by the caller rather than read here, so every row on one page
    is judged at one instant and a test can render a page at a chosen one. What it is
    for is :func:`_render_notification`'s expiry rendering, which ADR-0130 §7 requires
    and which no field on the record answers by itself.

    Args:
        page: The records the engine returned, oldest first.
        now: The instant to judge each record's expiry and actionability at.
        limit: The page size that was asked for.
        offset: How many rows were skipped.
    """
    if not page:
        # **An empty page is not the same claim as an empty store**, and only one of
        # the two is checkable from here. A page asked for past the end, or asked for
        # with `--limit 0`, is empty whatever the store holds — so saying "I am
        # holding nothing" there would be a false absence, and a confident one:
        # `--limit 0` is accepted, exactly as it is on every other listing.
        if offset or not limit:
            console.print(
                "[dim]No notifications on this page.[/] That says nothing about what "
                "is held — ask from the first page ('--offset 0' with a limit above 0) "
                "to see."
            )
            return
        console.print(
            "[dim]I am holding nothing for you.[/] Out of the box nothing reaches you "
            "unprompted — see 'assistant tune --help' for the three separate acts that "
            "arm it, and 'assistant notification-settings' for what is set now."
        )
        return
    console.print(f"[bold]{len(page)} notification(s)[/] I am holding, oldest first.")
    for record in page:
        _render_notification(record, now=now)
    if limit and len(page) == limit:
        console.print(
            f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]"
        )


def _render_notification(record: HeldNotification, *, now: datetime) -> None:
    """Render one held notification with what a person needs in order to act on it.

    **An expired record renders as expired**, which ADR-0130 §7 requires of any
    surface that enumerates one: expiry ends a notification's interruptibility and its
    actionability and deletes nothing, so the record is still listed and the listing
    has to say which side of that line it is on. No field answers it — the record
    carries the expiry instant and nothing else — so the caller's ``now`` is compared
    against it.

    **The comparison is the core type's and not this module's** (golden rule 3):
    :meth:`~ai_assistant.core.types.NotificationCandidate.is_perishable_at` is the
    boundary "spelled once so that a policy, a store and a suite cannot disagree about
    it", and this asks it rather than restating ``<=``. What the adapter supplies is a
    clock reading, which is what it already does when it stamps a ``FeedbackEvent``.

    **On a remote hub that reading is this device's, not the hub's** (ADR-0124), so a
    record within clock skew of its expiry may be labelled from the wrong side. It
    reaches expiry alone: dismissal and a ``DROP`` are stamped by the hub, and
    :func:`_render_notification_acts` treats either as final without consulting a
    clock. And what a mislabelled expiry costs is a hint, never a verb — the engine
    stays the authority on what any act does, and the id the user would type is on
    screen either way.

    Producer-supplied text — the summary, the detail, the class and the producer's own
    name — is neutralised for this terminal (``_safe``, ADR-0042 §4). The ruling, its
    reason and the conditions it is waiting on are this system's own closed
    vocabularies and are rendered through total matches.

    Args:
        record: The record to render.
        now: The instant to judge its expiry and actionability at.
    """
    candidate = record.candidate
    console.print(f"\n  [bold cyan]{_safe(record.id)}[/]")
    console.print(f"  [bold]{_safe(candidate.summary)}[/]")
    if candidate.detail is not None:
        console.print(f"  {_safe(candidate.detail)}")
    console.print(
        f"  [dim]Class:[/] {_safe(candidate.notification_class)} "
        f"[dim](noticed by {_safe(candidate.producer)})[/]"
    )
    _render_notification_ruling(record)
    console.print(f"  [dim]Noticed:[/] {_when(candidate.noticed_at)}")
    if candidate.expires_at is None:
        console.print("  [dim]Expires:[/] never — which is why it is held rather than urgent")
    elif _has_perished(candidate, now):
        console.print(
            f"  [yellow]Expired:[/] {_when(candidate.expires_at)} "
            f"[dim]— it is kept and readable, and it will not reach you[/]"
        )
    else:
        console.print(f"  [dim]Expires:[/] {_when(candidate.expires_at)}")
    _render_notification_acts(record, now=now)


def _has_perished(candidate: NotificationCandidate, now: datetime) -> bool:
    """Whether a candidate's declared moment has gone, as of ``now`` (ADR-0130 §5).

    The boundary is **not restated here**:
    :meth:`~ai_assistant.core.types.NotificationCandidate.is_perishable_at` is where
    §5's half-open test is "spelled once so that a policy, a store and a suite cannot
    disagree about" it, and this only supplies the absent-expiry case that predicate
    reads as "not perishable" rather than as "perished". Written once because the
    listing needs the answer twice — for the label, and for whether an act is worth
    offering — and two spellings of it would be two chances to disagree.

    Args:
        candidate: The proposal whose expiry to judge.
        now: The instant to judge it at, tz-aware.

    Returns:
        Whether it declared a moment and that moment has arrived. A candidate
        declaring none has not perished and never will (§5).
    """
    return candidate.expires_at is not None and not candidate.is_perishable_at(now)


def _render_notification_ruling(record: HeldNotification) -> None:
    """Say what was decided about one notification and why (ADR-0130 §5).

    A ``HOLD`` is explained by its **whole** failed set rather than by its reason
    alone: the reason is the set's first member (``NotificationDisposition``'s own
    rule), so naming it by itself would answer "why did you not tell me?" with one of
    several true answers and hide the rest — and the rest are exactly what a user
    would have to change. A ``DROP`` carries no set and is explained by its reason. An
    ``INTERRUPT`` failed nothing, so there is nothing to explain beyond the ruling.
    """
    match record.kind:
        case NotificationDispositionKind.INTERRUPT:
            console.print("  [dim]Ruled:[/] to reach you at the time")
        case NotificationDispositionKind.HOLD:
            console.print("  [dim]Ruled:[/] held for when you next look")
        case NotificationDispositionKind.DROP:
            console.print(f"  [dim]Ruled:[/] ruled out — {_condition_phrase(record.reason)}")
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(record.kind)
    for condition in record.failed:
        console.print(f"  [dim]Not now, because:[/] {_condition_phrase(condition)}")
    if record.dismissed_at is not None:
        console.print(f"  [dim]Dismissed:[/] {_when(record.dismissed_at)}")
    if record.dropped_at is not None:
        console.print(f"  [dim]Ruled out:[/] {_when(record.dropped_at)}")


def _render_notification_acts(record: HeldNotification, *, now: datetime) -> None:
    """Offer the two acts ADR-0130 §6 says a surface rendering one should offer.

    "Every ``INTERRUPT`` disposition carries its notification class, so any surface
    rendering it can offer the two acts that tune it in one step: dismissing the
    notification, and lowering that class's reach." Both are offered here, on every
    record still **actionable** rather than on an interruption alone — a held one is
    exactly what a user wants to dispose of or unblock, and it is the case #979 found
    unreachable.

    **Actionability is §7's three-part test taken in two parts, and the split is about
    whose clock decided each.** Dismissal and a reconsideration's ``DROP`` are
    *persisted*: the hub stamped them, and that they happened is a fact this device
    cannot be more current about — so either stamp ends the offer unconditionally,
    whatever this clock reads. Expiry is the limb with nothing stored; the record
    carries the instant and no verdict, so it is the one the reading answers.

    Asking :meth:`~ai_assistant.core.types.HeldNotification.is_actionable_at` for all
    three would put the two stamped limbs behind this device's clock as well, and a
    client running behind the hub would then offer ``dismiss`` on a record the hub has
    already dismissed — the engine answering ``False`` for a reason the user was shown
    no sign of, two lines under a rendered "Dismissed:" stamp. Offering an act that
    does nothing is a surface making a promise the engine will not keep, and a stale
    clock is the one case where that is avoidable for nothing.

    **Which direction to offer is read off the record and decided nowhere.** A record
    whose failed set names the reach condition is one the user's own setting is
    holding back, so the act that changes its outcome is raising that class; anything
    else is already allowed to reach them, and the act §6 names for that is lowering
    it.

    **Except where the set also names ``PERISHABLE``, and that exception is §5's
    rather than a refinement.** Declaring an expiry "is the whole of the escalation
    test": a candidate that commits to no moment "is held, never interrupted", and §6
    says in terms that such a record "is reached by no setting". Raising the class
    there is a real act with a real effect on every *other* record of the class and
    none whatsoever on this one — the write does re-arm it, the reconsideration does
    run, and it re-holds on the same condition. So the reach hint would be a surface
    promising an interruption that cannot happen, which is #979's own failure wearing
    the opposite face: there the act existed and had no door, here the door would open
    onto nothing. Dismissal stays offered, the lowering act stays offered because it
    still does something, and the reason is said rather than left to be inferred from
    a notification that never arrives.

    **The values are shell-quoted before they are escaped for the terminal**, because
    these two lines are meant to be *pasted*. An id and a class are both non-blank
    encodable text and neither forbids an interior space, so an unquoted hint for a
    class named ``calendar upcoming`` reads as a valid command that sets a different
    class. ``_safe`` is about Rich markup and control characters and answers a
    different question; quoting happens first, so what is escaped is the quoted form.
    The same exposure on the older ``answer``/``forget-question``/``revoke`` hints is
    #984 rather than a wider diff here.

    **And where quoting is not enough, no command is printed at all**
    (:func:`_is_pasteable`). ``_safe`` *replaces* a character a terminal must not be
    handed, so a class carrying a control character renders as a command that would
    set a different class — the failure quoting exists to prevent, arriving one step
    later and looking exactly like a working instruction. A wrong command is worse
    than none, so the record still renders and the acts are named in words instead.

    Args:
        record: The record whose acts to offer.
        now: The instant to judge its **expiry** at; the other two limbs are stamped.
    """
    if record.dismissed_at is not None or record.dropped_at is not None:
        return
    if _has_perished(record.candidate, now):
        return
    notification_class = record.candidate.notification_class
    if not _is_pasteable(record.id) or not _is_pasteable(notification_class):
        # Both acts go together here, because either value failing costs both hints.
        console.print(
            "  "
            + _uncopyable(
                "Its id or its class",
                "The 'dismiss' and 'tune' commands still take them, given the exact bytes.",
            )
        )
        return
    _print_hint(f"  [dim]Deal with it:[/] assistant dismiss {_argument(record.id)}")
    if NotificationCondition.PERISHABLE in record.failed:
        console.print(
            "  [dim]No reach setting can make this one interrupt:[/] it names no "
            "moment it stops mattering, and that is the whole of what earns an "
            "interruption."
        )
    wanted = (
        NotificationReach.INTERRUPT
        if NotificationCondition.REACH_INTERRUPT in record.failed
        and NotificationCondition.PERISHABLE not in record.failed
        else NotificationReach.OFF
    )
    _print_hint(
        f"  [dim]Tune the class:[/] assistant tune --class "
        f"{_argument(notification_class)} --reach {wanted.value}"
    )


def _is_pasteable(value: str) -> bool:
    r"""Whether ``_safe`` renders ``value`` faithfully enough to be typed back in.

    **Asked of ``_safe`` itself rather than by restating its rule**, so the two cannot
    drift: ``_safe`` both replaces characters a terminal must not be handed *and*
    escapes Rich markup, and only the first is lossy — Rich renders ``\\[red]`` back as
    the literal ``[red]``, so escaping changes what is written and not what is read.
    Comparing against :func:`~rich.markup.escape` alone therefore isolates the
    replacement exactly, and it stays correct if ``_safe``'s set of replaced characters
    ever changes.

    **A tab is refused separately, because ``_safe`` is not the only lossy step.**
    ``_safe`` keeps ``\t`` deliberately — a tab inside displayed *prose* is legitimate,
    and replacing it would corrupt what a producer wrote — but Rich expands it to the
    next tab stop when it renders, before any terminal is involved. So a hint carrying
    one is displayed as ``assistant revoke 'my    calendar'``: correctly quoted, and
    naming a source whose name holds spaces rather than a tab. That is this function's
    own failure arriving through a second channel, so it is named here rather than by
    tightening ``_safe`` — which would change every value this surface *displays* to fix
    the few it offers to be *copied*.

    Args:
        value: The value a printed command would carry.

    Returns:
        Whether the value survives being displayed.
    """
    return "\t" not in value and _safe(value) == escape(value)


def _render_notification_settings(preferences: NotificationPreferences) -> None:
    """Render the three standing settings that tune proactive contact (ADR-0130 §6).

    All three are shown whether or not the user has touched any of them, because each
    has a shipped default that is in force regardless — an empty store is a working
    policy, and rendering only what was set would present "I have decided nothing" as
    "nothing governs this". The default reach is named beside the classes for the same
    reason: it is what governs every class no row mentions, which on a fresh
    installation is all of them.
    """
    console.print("[bold]How far each class may reach you[/]")
    for row in preferences.reaches:
        console.print(
            f"  {_safe(row.notification_class)}: [bold]{row.reach.value}[/] "
            f"[dim]— {_reach_phrase(row.reach)}[/]"
        )
    console.print(
        f"  [dim]every other class:[/] [bold]{DEFAULT_NOTIFICATION_REACH.value}[/] "
        f"[dim]— {_reach_phrase(DEFAULT_NOTIFICATION_REACH)} (the shipped default)[/]"
    )
    console.print("\n[bold]Quiet hours[/] [dim](read in your configured timezone)[/]")
    if not preferences.quiet_windows:
        console.print("  [dim]none — no part of the day is quiet[/]")
    for window in preferences.quiet_windows:
        console.print(f"  {window.start_time:%H:%M}-{window.end_time:%H:%M}")
    console.print("\n[bold]Interruption budget[/]")
    console.print(
        f"  {preferences.interruption_budget} per {_hours(preferences.budget_window)}"
        f"{' [dim]— never interrupt[/]' if preferences.interruption_budget == 0 else ''}"
    )
    console.print("\n[dim]Change any of these with 'assistant tune'.[/]")


def _confirm_forget(_belief: Belief) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    The counterpart to :func:`_confirm` on the deletion path (I/O; ADR-0042 §6).
    Defaults to **no**: the question is about destroying something irreversibly, so a
    bare Enter must not be the answer that destroys it.
    """
    return typer.confirm("Forget it?", default=False)


def _egress_disclosure_phrase(provenance: DiscloserProvenance) -> str:
    """Say who disclosed one span, in words (ADR-0146 §1).

    **It says who, and nothing about what the value contains** — ADR-0178 §7's
    fifth clause forbids a surface presenting a ``SYSTEM_SELECTED`` marker as an
    assertion about what the text says, and ADR-0146 §2 makes provenance carried
    rather than derived. So the phrasing is the enum's own meaning restated: the
    user composed this span into the exchange, or this system put it there.

    Total over the enum through :func:`~typing.assert_never`, so a third member
    would fail the type check rather than render as an empty string.
    """
    match provenance:
        case DiscloserProvenance.USER_AUTHORED:
            return "you composed it"
        case DiscloserProvenance.SYSTEM_SELECTED:
            return "this system selected it"
    assert_never(provenance)


def _egress_destination_line(member: ConfirmationDestination) -> str:
    """One member of the canonical destination set, as `core` derived it (ADR-0178 §7).

    The set is read from
    :attr:`~ai_assistant.core.types.ConfirmationEgress.canonical_destination_set`
    and rendered; this adapter deduplicates nothing, orders nothing and infers
    nothing, because a second derivation of one fact is business logic in an
    adapter (golden rule 3) and would put a recipient on screen the ruling was not
    taken over.

    **The account arm is named as a destination rather than as an absence.** Where
    the spans carry no destination the set is the connected account (ADR-0148 §2's
    third clause), and §7 requires the surface to name it rather than showing no
    recipients.
    """
    if member.account_identity is not None:
        return f"the connected account {_safe(member.account_identity)}"
    return _recipient_line(member.protocol, member.canonical)


def _recipient_line(protocol: DestinationProtocol | None, canonical: str | None) -> str:
    """The selected-recipient arm of a canonical destination set member.

    Shared by the confirmation's set and the recorded binding's, because ADR-0186
    §7 renders a history row's recipients under **ADR-0178 §7's** obligations rather
    than a second set of its own: "a second, differently worded floor would be a
    second vocabulary to keep in step with the first, and the failure would be a
    history that renders a disclosure the card showed, or shows one it did not". One
    function is that argument made structural — the two surfaces cannot drift
    because there is nothing to drift.

    The two member types differ only in their **account** arm, which is why the
    account is each caller's and the recipient is this function's:
    :class:`~ai_assistant.core.types.ConfirmationDestination` carries the account's
    identity where :class:`~ai_assistant.core.types.CanonicalDestination` carries
    the whole account (ADR-0178 §3).

    Args:
        protocol: The member's protocol, as the value carries it.
        canonical: The member's canonical form, as `core` derived it.

    Returns:
        The line for one selected recipient, neutralised for this terminal.
    """
    named = "" if protocol is None else protocol.value
    return f"{_safe(canonical or '')} [dim]({_safe(named)})[/]"


def _egress_span_line(span: EgressSpan) -> str:
    """One occurrence of the payload description, whole (ADR-0178 §7).

    **A description, never the payload.** A span states an argument, a position, a
    provenance, an extent and sometimes a tier; it holds no content (ADR-0150 §10),
    so nothing here presents an extent as the text or a marker as an assertion
    about it.

    **Both forms where the occurrence carries a destination, and neither invented
    where it does not.** :attr:`~ai_assistant.core.types.EgressSpan.destination` is
    optional, so a destination-less span is rendered as the payload-description
    span it is — by its argument and position, its provenance and its extent, and
    its tier where it states one — and names no recipient. Where a destination is
    present both forms are shown and each is labelled: nothing reconstructs a
    supplied form from a canonical one, and nothing presents a canonical form as
    the form the user or the model wrote (ADR-0148 §14).
    """
    where = _safe(span.argument) if span.index is None else f"{_safe(span.argument)}[{span.index}]"
    facts = [_egress_disclosure_phrase(span.provenance), f"{span.extent} code points"]
    if span.tier is not None:
        facts.append(f"tier {_safe(span.tier.value)}")
    occurrence = span.destination
    if occurrence is None:
        head = "names no destination"
    else:
        head = (
            f"to {_safe(occurrence.canonical)} [dim]({_safe(occurrence.protocol.value)})[/], "
            f"as supplied: {_safe(occurrence.supplied)}"
        )
    return f"{where} — {head}; " + "; ".join(facts)


def _egress_origin_line(egress: ConfirmationEgress) -> str:
    """The call's origin, at the strength the predicate carries (ADR-0181 §6).

    **A property of the call, never of a span.** What the boolean records is whether
    the material this system *selected* into the model call that produced this
    request included any record for which ``rests_on_recorded_external_content`` is
    true (ADR-0106 §1). ADR-0181 §2's third clause refuses to mint a per-span
    marker, so this line names no argument, no position, no destination and no
    payload span, and is rendered beside the occurrences rather than against one.

    **Neither state names a source, or a kind of source.** ADR-0181 §6's second
    clause bars "from a source you connected" in terms: ADR-0098 §1's class is
    wider than connected sources, reaching a tool or MCP result, a provider's error
    text and a third party's speech captured by a spoke. The subject here is the
    selection this system performed, which is the one actor the value can honestly
    name.

    **The ``False`` arm is not an assurance and is worded so it cannot be read as
    one.** It says no *selected record carried the marker* — not that no external
    content was involved, which is ADR-0181 §7's residual and is not closed by
    anything here. It is a self-contained sentence rather than a "no" against the
    ``True`` arm's wording, because a reader in the ``False`` case never sees the
    ``True`` arm and would have no antecedent for a bare negation.

    **Both arms are rendered, which is the point of the clause** (§6's fourth): a
    fact shown only when it is alarming is one a user learns to read as an alarm,
    and its absence as clearance. Neither arm is a detection, a score, a risk level
    or a claim that the call is malicious (§6's sixth, §7's second).

    Args:
        egress: The egress facts this confirmation is about.

    Returns:
        The sentence rendered beside the floor, for whichever state the call carries.
    """
    return _origin_line(planned_with_external_content=egress.planned_with_external_content)


def _origin_line(*, planned_with_external_content: bool) -> str:
    """The two **recorded** origin states, in words (ADR-0181 §6).

    Split out of :func:`_egress_origin_line` so a history row reaches the same two
    sentences (ADR-0186 §7): the third state is
    :func:`_recorded_origin_line`'s, and it is distinct from these because the
    *fact* is distinct, not because a second surface worded the first two
    differently. Everything :func:`_egress_origin_line` documents about the two arms
    — that neither names a source, that the ``False`` arm is a self-contained
    sentence and not an assurance, and that neither is a detection — holds here
    unchanged, because these are those sentences.

    Args:
        planned_with_external_content: The value the binding records.

    Returns:
        The sentence for whichever of the two recorded states the call carries.
    """
    if planned_with_external_content:
        return (
            "material this assistant selected, which includes a record marked as "
            "resting on recorded external content"
        )
    return (
        "material this assistant selected, in which no record is marked as "
        "resting on recorded external content"
    )


def _render_confirmation_egress(egress: ConfirmationEgress) -> None:
    """What ADR-0148 §8's fourth clause requires, before the answer is collected.

    Three things, and a confirmation naming the tool and not the recipients is not
    a confirmation of an egress call: the connected account's **identity**, the
    canonical destination set **in both forms**, and the **payload description**.

    **The set and the occurrences are both rendered, and that is not redundancy**
    (ADR-0178 §7). They answer different questions: the set is what the policy
    ruled over and is deduplicated, so it answers "how many people is this going
    to"; the occurrences answer ADR-0150 §10's third clause, so one recipient named
    by ``to`` and again by ``bcc`` is one member of the set and **two** disclosures
    here. A surface showing only the set has hidden a disclosure; one showing only
    the occurrences has shown a list the user must deduplicate in their head.

    **Every span, none omitted and none reordered.** The tuple is rendered in the
    binding's own order, which is the artifact the ruling was taken over.

    **ADR-0181 §6 adds one line and moves none of the others.** The call's origin is
    rendered beside this floor rather than in place of any part of it, and nothing
    above is suppressed, reordered or de-emphasised on the strength of it (§6's
    sixth clause). It sits after the account and before the recipients because it is
    a property of the call rather than of a span — putting it among the occurrences
    would read as the per-span attribution §2's third clause refuses to mint.
    """
    console.print(f"  [bold]Account:[/] {_safe(egress.account_identity)}")
    console.print(f"  [bold]Planned over:[/] {_egress_origin_line(egress)}")
    console.print("  Goes to:")
    for member in egress.canonical_destination_set:
        console.print(f"    {_egress_destination_line(member)}")
    console.print("  Describing:")
    if not egress.spans:
        console.print("    [dim](the payload description names no span)[/]")
    for span in egress.spans:
        console.print(f"    {_egress_span_line(span)}")


def _render_confirmation(confirmation: Confirmation) -> None:
    """Render a parked action so a person can judge it (ADR-0042 §4, ADR-0178 §7).

    **An egress confirmation owes more than the four content members**, and until
    ADR-0178 landed no surface in this tree could pay it: ADR-0148 §8's fourth
    clause has required the connected account's identity, the canonical
    destination set in both forms and the payload description since 2026-08-13,
    and none of the three was reachable from ``Confirmation``. It is now
    :attr:`~ai_assistant.core.types.Confirmation.egress`, and
    :func:`_render_confirmation_egress` is the floor.

    **A confirmation whose ``egress`` is ``None`` renders exactly as it did**, and
    asserts none of it (ADR-0178 §7's last clause). What the absence states is that
    the ruling was taken over no egress binding and nothing more, so this makes no
    claim that the call transmits nothing or reaches no recipient — it simply says
    nothing about recipients, which is what it is entitled to say.

    **``parameters`` is still the driven step's own arguments, pre-binding**, and
    ADR-0177 §8's surviving sub-clauses are why it keeps a heading of its own: the
    rendered arguments are not the canonical destination set, and a flat
    destination appearing among them is not a canonical one. The set now arrives
    *beside* them rather than instead of them, which makes that confusion easier to
    make and the separation more load-bearing, not less.

    Every value is neutralised for this terminal on the way out (:func:`_safe`),
    the new members included: ``argument`` is a caller-influenced key (ADR-0150
    §13) and a ``supplied`` form is a string a model produced.
    """
    console.print("\n[bold yellow]Confirmation required[/]")
    console.print(f"  Tool: {_safe(confirmation.tool_id)} — {_safe(confirmation.tool_description)}")
    if confirmation.parameters:
        console.print("  With:")
        for key, raw in confirmation.parameters.items():
            console.print(f"    {_safe(str(key))} = {_safe(str(raw))}")
    if confirmation.egress is not None:
        _render_confirmation_egress(confirmation.egress)
    console.print(f"  Why: {_safe(confirmation.reason)}")


def _prompt_for_approval(confirmation: Confirmation) -> bool:
    """Render the confirmation and read the human's yes/no (I/O; ADR-0042 §6)."""
    _render_confirmation(confirmation)
    return typer.confirm("Proceed?", default=False)


def _confirm(_confirmation: Confirmation) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    Used by the ``resume`` flow, where :func:`_drive_resume` renders each recovered
    action before prompting, so rendering here too would show it twice (I/O; §6).
    """
    return typer.confirm("Proceed?", default=False)


# --- rendering the audit trail (ADR-0186 §7, §8) ----------------------------
# A history row is not a question, and that difference is the whole of this
# block. ADR-0178 §7's content obligations are **borrowed** rather than restated,
# so the same helpers render the same facts here as on a confirmation card; what
# is added is the two things a record needs that a question does not — a third
# origin state (ADR-0184 §2), and a bar on presenting a ruling as an event.


def _decision_headline(outcome: PermissionOutcome) -> str:
    """What the ruling said, in one word (ADR-0186 §7, §8).

    **Past tense, and about the ruling rather than about the call.** §8's third
    clause bars presenting a decision as a transmission — the trail "bounds
    resolutions and not executions", so a resolved ``ALLOW`` says a call was
    permitted and says nothing about whether, or how many times, it ran. "Sent"
    beside an ``ALLOW`` is the specific regression this wording exists against, and
    it is the one a status column reaches for first.

    **A ``CONFIRM`` is a question that was asked, and is never resolved by this
    line** (§7's fifth clause). Whether it was answered is a *different row*, which
    may lie outside a bounded page, so nothing here renders one as denied, as
    allowed, as expired or as awaiting anything.

    Total over the enum through :func:`~typing.assert_never`, so a fourth outcome
    would fail the type check rather than render as an empty headline.
    """
    match outcome:
        case PermissionOutcome.ALLOW:
            return "[green]allowed[/]"
        case PermissionOutcome.DENY:
            return "[red]refused[/]"
        case PermissionOutcome.CONFIRM:
            return "[yellow]asked[/] [dim](a question put to you)[/]"
    assert_never(outcome)


def _recorded_origin_line(binding: EgressBinding | OriginUnrecordedBinding) -> str:
    """The call's origin in **three** states, none rendered as any other (ADR-0186 §7).

    The two recorded states are :func:`_origin_line`'s, unchanged — a history row
    says the same thing about a recorded origin that the confirmation card said.
    The third is this function's whole reason to exist.

    **The third state is a rendered state and not a rendered absence**, which is
    ADR-0184 §2's second test read at the surface. The reason
    :class:`~ai_assistant.core.types.OriginUnrecordedBinding` carries the account,
    the occurrences and the payload description instead of being a marker is that
    the row's facts are the user's to read; a surface that then left the origin
    blank would have thrown away the one thing the value was minted to say. So it
    is refused as ``False``, as "no", as an empty value, as an omission, and as
    anything a reader could mistake for either of the other two — it states what
    happened to the *record*, which is the only honest subject available.

    **Rendered in all three states, for ADR-0181 §6's reason**: a fact shown only
    when it is alarming is one a user learns to read as an alarm, and its absence as
    clearance. None of the three is a detection, a score, a risk level or a claim
    that the call was malicious (ADR-0181 §7, ADR-0186 §8).

    Args:
        binding: The binding the ruling was taken over, as the row records it.

    Returns:
        The sentence for whichever of the three states this row is in.
    """
    if isinstance(binding, OriginUnrecordedBinding):
        return (
            "not recorded — this ruling was made before this assistant kept the "
            "origin of a call, so the record states nothing either way about the "
            "material it selected"
        )
    return _origin_line(planned_with_external_content=binding.planned_with_external_content)


def _recorded_destination_line(member: CanonicalDestination) -> str:
    """One member of a recorded binding's canonical destination set (ADR-0186 §7).

    :func:`_egress_destination_line` over the type a **binding**'s own derived set
    carries. The set is read from
    :attr:`~ai_assistant.core.types.EgressBinding.canonical_destination_set` — as
    `core` derived it — and this adapter deduplicates nothing, orders nothing and
    infers nothing, because a second derivation of one fact is business logic in an
    adapter (golden rule 3) and would put a recipient on screen the ruling was not
    taken over.

    **The account arm names the identity and never the reference.**
    :class:`~ai_assistant.core.types.CanonicalDestination` carries the whole
    :class:`~ai_assistant.core.types.BoundAccount`, and ADR-0148 §6 says the
    connection reference "is not something an account can be recognised by" and is
    never shown to the user. So the reduction ADR-0178 §3 performs for a
    confirmation is performed here too, by this renderer rather than by a type,
    and for the same reason.
    """
    if member.account is not None:
        return f"the connected account {_safe(member.account.identity)}"
    return _recipient_line(member.protocol, member.canonical)


def _render_recorded_egress(binding: EgressBinding | OriginUnrecordedBinding) -> None:
    """ADR-0178 §7's content obligations over a recorded binding, in full (ADR-0186 §7).

    :func:`_render_confirmation_egress`'s facts in its order — the connected
    account's identity, the call's origin, the canonical destination set in both
    forms, and the payload description — because they *are* the same facts:
    ADR-0178 §5 builds a ``ConfirmationEgress`` from the recorded decision, so a
    second wording here would be a second vocabulary to keep in step with the first.

    **The labels are the one thing that changes, and the change is §8's third
    clause.** A card says where a call is going, because it has not gone; a row says
    what a ruling was taken over, because the trail bounds resolutions and not
    executions and no row knows whether anything ran. "Goes to" on a history row
    would be a transmission claim in two words.

    **Every span, none omitted, none reordered, and none truncated** (§7's
    last-but-one clause): a surface that cannot render a row whole renders fewer
    rows, not partial ones, so there is no elision here and no count standing in for
    an occurrence.
    """
    console.print(f"  [bold]Account:[/] {_safe(binding.account.identity)}")
    console.print(f"  [bold]Planned over:[/] {_recorded_origin_line(binding)}")
    console.print("  Ruled over these recipients:")
    for member in binding.canonical_destination_set:
        console.print(f"    {_recorded_destination_line(member)}")
    console.print("  Payload described as:")
    if not binding.spans:
        console.print("    [dim](the payload description names no span)[/]")
    for span in binding.spans:
        console.print(f"    {_egress_span_line(span)}")


def _authorisation_line(decision: PermissionDecision) -> str:
    """What authorised an ``ALLOW``, in exactly three states (ADR-0193 §11).

    §11 extends ADR-0186 §7 by **one** fact and changes none of its others, so this
    line is appended to the row rather than displacing anything: nothing above it is
    suppressed, reordered or de-emphasised on the strength of what it says (§11's
    last clause).

    **The three states, and the discriminator each is read off.** A decision of the
    user about *that* call is ``resolves`` set with ``authorised_by`` equal to it; a
    standing authorisation this row names is ``authorised_by`` set with ``resolves``
    unset; the policy's own rules, resting on no decision of the user, is
    ``authorised_by`` unset. That is ADR-0193 §6's discriminator — the route is told
    apart by whether ``resolves`` is set, with no field added to carry the basis
    itself — read at the surface.

    **Derived from the row alone.** Nothing here reads the grant store, holds a
    ``RecipientGrants`` or a ``RecipientGrantStore``, or resolves an
    ``authorised_by`` (§11's second clause). That is golden rule 3 and ADR-0186 §1's
    own limit at once: a renderer given the store face would hold ``record`` and
    ``clear``, and a remote client could not perform the read at all without a
    second contract.

    **The second state says exactly what the row says and nothing more** (§11's
    third clause): that this decision *names* a standing authorisation. It does not
    state or imply that the named grant exists, is held by the store, is live, is
    unrevoked, has not expired, was validated, or covers anything now — ADR-0186
    §8's first clause, which names a grant in terms, read on this fact. The bar on
    "was validated" does not contradict ADR-0193 §6, which requires ``record`` to
    validate every route-(b) row it writes: a surface cannot tell a row written
    before that implementation from one written after, the row carries no mark
    saying which it is, and no surface has a read with which to find out. So what §6
    makes true of the system is not a claim this renderer is entitled to make about
    the row in front of it.

    **The third state is a positive fact and never an absence** (§11's eighth
    clause). It is not rendered as a blank, an omission or a failure to record:
    ADR-0021 §5's floor bars an auto-granted ``ALLOW`` only for a **non-empty**
    ``discloses``, so a non-disclosing, known-cost action reaching ``ALLOW`` with
    ``authorised_by`` unset is conforming and ordinary. Forcing such a row into
    either other state would assert a user decision that was never taken. This is
    ADR-0186 §7's three-origin-state discipline, read on a second three-state fact.

    **``authorised_subject`` is rendered not at all**, which §11's fifth clause
    permits beside rendering it opaque. Nothing here presents it as a verification,
    a match, a badge, an assurance or a difference from another row; the comparison
    ADR-0193 §6's digest makes possible is an out-of-band one over two exports, and
    this is not the render path for it.

    **Each state is rendered on §11's own condition and on no wider one**, which is
    what keeps the enumeration the ADR's rather than this function's. The third is
    conditioned on ``authorised_by`` unset **and on nothing else**, so a row carrying
    a ``resolves`` and no ``authorised_by`` is the third state by the clause as
    written. The second is conditioned on ``resolves`` unset, so it is never widened
    to cover a resolving row.

    **A row satisfying none of the three conditions is refused rather than rendered,
    and there is no fourth state.** ``PermissionRuling`` refuses ``authorised_by`` on
    a non-``ALLOW`` and ``AuditTrail.record`` refuses a *resolving* ``ALLOW`` whose
    ``authorised_by`` is not its own ``resolves``, which together make §11's three
    states total over every row a trail can return — the totality the section claims
    when it says "the discriminator is total because ``authorised_by`` and
    ``resolves`` are". The types alone are looser: a row carrying ``resolves`` and a
    *different* ``authorised_by`` validates, and this surface renders whatever the
    operation hands it, over the wire, from a hub this adapter does not own.

    No state's claim is true of such a row — it answers a confirmation about this
    call and rests on something that is not that confirmation — so assigning it one
    would assert a basis the record does not determine, and rendering a fourth
    would be a state §11 does not have. What is left is the refusal ADR-0186 §7
    already names: "a surface that cannot render a row whole renders **fewer rows**,
    not partial ones". The listing takes that to its end and renders none, exactly as
    it does for an unreadable trail — a refusal reaches the user as itself, and no
    row is invented. The record is still reachable: ``assistant export-decisions``
    is a faithful copy (§9) and states this shape as the bytes it is, which is the
    artifact's job and not this listing's.

    :class:`~ai_assistant.core.errors.InvalidResolutionError` is the refusal's name
    because ``core`` already gives this exact condition that name — it is raised
    "when the resolving ruling's ``authorised_by`` does not match its ``resolves``" —
    so the adapter names the trail's own rule rather than authoring one, which is
    golden rule 3. It is an :class:`~ai_assistant.core.errors.AssistantError`, so
    :func:`_drive_decisions`' existing boundary catches it and
    :func:`_render_error` neutralises every value in the message for this terminal.

    Args:
        decision: The recorded ruling, whose outcome the caller has already
            established is ``ALLOW``.

    Raises:
        InvalidResolutionError: If the row is an ``ALLOW`` that satisfies none of
            §11's three conditions — a resolving decision whose ``authorised_by`` is
            neither unset nor its own ``resolves``.

    Returns:
        The line's markup, with every value from the row neutralised for this
        terminal (ADR-0186 §7's last clause, ADR-0042 §4) — an ``authorised_by`` is
        a :data:`~ai_assistant.core.types.DurableIdentifier` and not a string a
        policy is free to shape, but it is interpolated into adapter-authored text
        exactly as ``reason`` is, and the neutralisation is what makes that safe
        without depending on another type's invariant.
    """
    authorised_by = decision.ruling.authorised_by
    if authorised_by is None:
        return "[bold]Authorised by:[/] the policy's own rules, resting on no decision of yours"
    if decision.resolves is None:
        return (
            "[bold]Authorised by:[/] a standing authorisation this ruling names, "
            f"recorded as {_safe(authorised_by)} [dim](what the row names, and no more)[/]"
        )
    if authorised_by == decision.resolves:
        return (
            "[bold]Authorised by:[/] a decision you took about this call, "
            f"recorded as {_safe(authorised_by)}"
        )
    msg = (
        f"decision {decision.id!r} answers {decision.resolves!r} but rests on "
        f"{authorised_by!r}; no ruling an audit trail accepts carries both, and this "
        f"listing states what authorised a call rather than guessing between them. "
        f"'assistant export-decisions' writes the record as it stands."
    )
    raise InvalidResolutionError(msg)


def _render_decision(decision: PermissionDecision) -> None:
    """One recorded ruling, whole (ADR-0186 §7).

    **What is rendered is §7's enumeration and the two identifiers that make it
    legible.** The clause requires the ruling's outcome, its reason, the instant it
    was decided, and the recorded declaration's own identifier and capability — read
    from the row and never from a registry, because ADR-0021 §1 embeds the
    declaration verbatim so that "the trail stays readable without the registry".
    The decision's own id is rendered beside them because §7's resolution clause
    obliges an answer to *name* the question it answers, and an id nothing prints is
    a name nothing can be found by.

    **What is deliberately not rendered is as load-bearing.**
    :attr:`~ai_assistant.core.types.ToolDefinition.reads`, ``writes`` and
    ``discloses`` are absent, and their absence is §8's fifth clause rather than an
    oversight: they are ceilings on what a tool *may* reach, not per-call
    measurements (ADR-0016 §3), and a tier reach printed beside a recipient list
    would assert the measurement ADR-0016 §3 declines to offer. Nothing here
    computes, displays or implies
    :meth:`~ai_assistant.core.types.PermissionDecision.authorises` either (§8's
    second clause), and no answer, approve or deny control appears on a row (§8's
    last): ``pending_confirmations`` and ``resume`` are where a question is
    answered, and ADR-0184 §8's bar on a confirmation shape for an unrecorded
    origin binds here as it binds everywhere.

    **The digest is a digest.** It is never labelled as, rendered as or expanded
    into the payload (§8's fourth clause) — what it does is bind the arguments the
    ruling was taken over, which is exactly what the record holds and exactly what
    the line says.

    **A ``None`` binding asserts nothing** (§7's fourth clause). No recipient, no
    account and no origin is rendered, and none is denied: ``None`` means the
    request was not an egress call (ADR-0150 §1) and continues to mean exactly that.

    **An ``ALLOW`` also says what authorised it, in three states** (ADR-0193 §11) —
    :func:`_authorisation_line`, appended after §7's own fields and displacing none
    of them. The line is rendered for an ``ALLOW`` and for no other outcome, which
    is §11's scope and also ``PermissionRuling``'s own rule that a refusal and a
    question rest on no authorisation.

    Every value is inserted as data and neutralised for this terminal (§7's last
    clause, ADR-0042 §4). Being read from an append-only store relaxes nothing:
    ``reason`` is policy-authored text, a ``supplied`` destination form is a string
    a model produced, and ``argument`` is a caller-influenced key (ADR-0150 §13).
    """
    console.print(
        f"  {_decision_headline(decision.ruling.outcome)} "
        f"[dim]{_decided_at(decision.decided_at)}[/] [dim]{_safe(decision.id)}[/]"
    )
    console.print(
        f"  [bold]Tool:[/] {_safe(decision.tool.id)} "
        f"[dim](capability {_safe(decision.tool.capability)})[/]"
    )
    console.print(f"  [bold]Why:[/] {_safe(decision.ruling.reason)}")
    console.print(
        f"  [bold]Digest:[/] {_safe(decision.parameters_digest)} "
        "[dim](a digest, never the arguments)[/]"
    )
    if decision.resolves is not None:
        console.print(f"  [bold]Answers the question:[/] {_safe(decision.resolves)}")
    if decision.ruling.outcome is PermissionOutcome.ALLOW:
        console.print(f"  {_authorisation_line(decision)}")
    if decision.egress_binding is not None:
        _render_recorded_egress(decision.egress_binding)
    console.print()


def _render_decisions(recorded: tuple[PermissionDecision, ...], *, limit: int) -> None:
    """The bounded listing, and the three things the page itself has to say.

    **Order is the engine's claim about when a ruling was made, and about nothing
    else** (ADR-0186 §2). It is not insertion order, the two disagree whenever rows
    are appended out of order, and no position here is a statement about when
    anything was *done*.

    **Liveness is not derivable from history** (§8's first clause). A row states
    that a ruling was made — never that it still stands, that a grant is current,
    that an account is connected, or that a definition is still registered under the
    identifier the row records. That sentence is printed rather than assumed,
    because the reader who most needs it is the one treating this list as a
    permissions screen.

    **A page's silence is a fact about the page** (§7's fifth clause). A resolution
    may lie outside a bounded page, so an unresolved ``CONFIRM`` on screen is never
    rendered as denied, as allowed, as expired or as awaiting anything, and the
    footer says so in the one place a reader would otherwise infer it.

    Args:
        recorded: The page, in the operation's order.
        limit: The bound that was asked for, so a full page can say it is one.
    """
    if not recorded:
        console.print("[yellow]Nothing recorded.[/] No ruling has been made yet.")
        return
    console.print(f"[bold]{len(recorded)}[/] ruling(s), newest ruling first:\n")
    for decision in recorded:
        _render_decision(decision)
    if len(recorded) == limit:
        console.print(
            f"[dim]Showing {limit}. Ask for more with --limit; there is no total "
            "count, and 'assistant export-decisions' writes the whole record.[/]"
        )
    console.print(
        "[dim]Each row is a ruling that was made. It does not say the ruling still "
        "stands, that a grant is current, that an account is still connected, or that "
        "the tool is still registered under the identifier above — and it does not say "
        "the call ever ran: this record bounds what was decided, not what was carried "
        "out.[/]"
    )
    console.print(
        "[dim]A question and the answer to it are two rows. An answer can fall outside "
        "this page, so a question with nothing answering it here is a fact about the "
        "page and not about the question.[/]"
    )
    console.print(
        "[dim]A digest binds the arguments a ruling was taken over. The arguments "
        "themselves are not in this record and are not shown.[/]"
    )


# --- rendering the read trail (ADR-0186 §10, ADR-0185 §1, §2, §7) -----------
# The second pair's rendering, and the block above is its model rather than its
# template. What is inherited is §7's last two clauses and §8's bars (ADR-0186
# §10); what is *not* is §7's egress content floor, which is about a binding no
# read record carries. What is added is this store's own: six outcomes, opened-ness
# as a function of the outcome and undeterminable on one of them, and a horizon.


def _checked_at(instant: datetime) -> str:
    """The instant a read's grant check resolved, at :func:`_decided_at`'s precision.

    **The same format for a different fact, deliberately.** ADR-0186 §10 inherits
    §7's clause that no surface "omits, truncates, summarises, samples or counts in
    place of any part of what it renders", so a minute-grained instant would be a
    truncation here for the reason it is one there — and this store makes the case
    stronger, not weaker: a driver checking a revoked source on a schedule writes
    rows seconds apart, and at ``%H:%M`` a page of them renders as one instant
    repeated.

    **What the value is remains this store's own.** It is the instant the *first
    grant check resolved*, read immediately after that and before ``read()``
    (ADR-0185 §2) — not when the read finished, which no field records. And it is
    **not** the ordering key: ADR-0185 §6 orders the trail by recording order and
    forbids deriving an order by comparing these values, so two rows may carry
    instants that disagree with their positions. :func:`_render_reads` says so
    where a reader would otherwise infer the opposite.

    A pure formatting of a value that arrived on the record — no clock is read
    here, and none may be (golden rule 3).
    """
    return _decided_at(instant)


def _read_ending(outcome: ReadOutcome) -> tuple[str, str]:
    """How the attempt ended: the word for it, and what it says about opening.

    **Opened-ness is a function of the outcome and is not recorded a second time**
    (ADR-0185 §1), so it is *rendered* from the outcome rather than looked for on
    the record — a boolean beside the field was refused for ADR-0106 §2's reason,
    and a renderer inventing one here would be minting that second spelling at the
    surface instead. Five of the six determine it; on ``FAILED`` it is "not
    determinable from the record", and this says so rather than inferring in either
    direction — a reader can refuse before starting work at all or fail with the
    bytes already in hand, and ADR-0093 §8 makes both cross the seam as the same
    error.

    **Each word is about the attempt, never about what came of it** (ADR-0186 §8's
    third clause, one store over). A completed attempt says the reading was
    admitted for its use and says nothing about whether the use ran, what it kept,
    or whether anything reached the user — those are memory's record and the
    notification store's (ADR-0185 §10). "Remembered" beside a completed row is the
    specific regression this wording exists against.

    **The two unanswerable outcomes stay separate from their answered twins**
    (ADR-0185 §1). "There was no live grant" and "I could not find out whether
    there was one" are different facts about the user's authorisation, and folding
    them would put a claim into a record whose premise is that it fabricates none.

    **The word is the enum's own**, so what a user reads and what an exported row
    carries are the same six words, and a reader comparing a screen with a
    ``reads.json`` needs no glossary between them.

    **Two values rather than one line**, because a row's identifier is what a user
    quotes and an identifier that lands in a different column on every row cannot
    be found: the clause is long on three outcomes and short on three, so folding
    it into the headline pushes the instant and the id past the wrap on exactly the
    rows the reader is looking hardest at.

    Total over the enum through :func:`~typing.assert_never`, so a seventh outcome
    would fail the type check rather than render as an empty ending.

    Args:
        outcome: How the attempt ended, as the record states it.

    Returns:
        The outcome's own word, coloured, and the sentence that says whether the
        source was opened and what followed.
    """
    match outcome:
        case ReadOutcome.COMPLETED:
            return "[green]completed[/]", "opened, and the grant still stood at the re-check"
        case ReadOutcome.REFUSED:
            return "[red]refused[/]", "not opened: you allowed no live grant for it"
        case ReadOutcome.UNANSWERED:
            return "[red]unanswered[/]", "not opened: I could not find out whether you allowed it"
        case ReadOutcome.FAILED:
            return "[yellow]failed[/]", "the read raised; whether it was opened is not recorded"
        case ReadOutcome.DISCARDED:
            return (
                "[yellow]discarded[/]",
                "opened, then the grant was gone at the re-check, so the reading was dropped whole",
            )
        case ReadOutcome.UNCONFIRMED:
            return (
                "[yellow]unconfirmed[/]",
                "opened, then the re-check could not be answered, so the reading was dropped whole",
            )
    assert_never(outcome)


def _read_grant_line(record: SourceReadRecord) -> str:
    """The grant the attempt ran under, or the absence that is itself a fact.

    ``grant`` is ``None`` **exactly** on ``REFUSED`` and ``UNANSWERED`` and is set
    on every other outcome (ADR-0185 §2, checked at construction), so the absence
    states something about the check rather than something missing from the row.

    **The two absences are two different sentences, and that is the whole reason
    this takes the record rather than the field** (ADR-0185 §1). On ``REFUSED``
    there was no live grant; on ``UNANSWERED`` the check *raised*, so whether one
    existed is not known. One wording for both would put the claim "there was no
    live grant" onto the row where it is precisely unknown — the fold ADR-0185 §1
    names, arriving at the surface rather than in the store, and contradicting the
    row's own ending line one line above it. ADR-0097 §5 is the older statement of
    the same rule: "a store fault and a withdrawn grant are different facts and an
    operator must be able to tell them apart."

    **The pointer is one-way and is never resolved here** (ADR-0185 §8). Nothing
    joins back from a grant to its reads, and an id that no longer resolves —
    after a withdrawal, or a cleared store — is **legible history rather than
    corruption**: the row says truthfully what the attempt cited at the time. So
    this renders the id as recorded, claims nothing about whether it still
    resolves, and looks nothing up.

    Args:
        record: The row, for its ``grant`` and for the outcome that says what an
            absent one means.

    Returns:
        The recorded id with what it is, or the sentence naming which absence
        this is.
    """
    if record.grant is not None:
        return (
            f"{_safe(record.grant)} [dim](what the attempt cited then; it is not looked up now)[/]"
        )
    if record.outcome is ReadOutcome.UNANSWERED:
        return "[dim]none cited — the check did not answer, so whether you allowed it is unknown[/]"
    # The remaining ungranted outcome is ``REFUSED``: ADR-0185 §2's construction
    # invariant refuses a ``None`` grant on the other four, and a model that
    # admitted a fifth would be a change to that ADR rather than to this branch.
    return "[dim]none — you had allowed no live grant when I checked[/]"


def _render_read(record: SourceReadRecord) -> None:
    """One recorded read attempt, whole (ADR-0186 §7's last two clauses, §10).

    **All seven of the record's fields are rendered** (ADR-0185 §2): its own id,
    the source, the use, the instant the check resolved, the outcome, the grant,
    and the count. Nothing here truncates, summarises, samples or counts in place
    of any part of one, so a narrow terminal gets fewer rows rather than shorter
    ones.

    **What is deliberately absent is what the record does not hold.** There is no
    content, no entry, no path and no configured location, and no string derived
    from any of them (ADR-0185 §2) — :attr:`source` is the reader's *declared
    identity* and :attr:`produced` is a count rather than a thing. A surface
    reaching for "what did it say" would be reaching for something that was never
    written down, which ADR-0004 §5 and ADR-0093 §8 forbid being written down.

    **Nothing here derives liveness or authorisation from history** (ADR-0186 §8,
    ADR-0185 §8). A row is not consulted to decide whether a source is granted,
    what a grant's scope is, or what a source's grant history is;
    ``SourceGrants.live`` remains the only answer to whether a read may happen, and
    ``assistant granted`` is the surface that asks it.

    Every value is inserted as data and neutralised for this terminal (ADR-0186
    §7's last clause, ADR-0042 §4). Being read from an append-only store relaxes
    nothing: a source is the identity a reader *declares*, stored byte for byte
    with nothing normalised away (ADR-0185 §2), which is exactly the kind of value
    a renderer must not hand a terminal unescaped.
    """
    word, ending = _read_ending(record.outcome)
    console.print(f"  {word} [dim]{_checked_at(record.checked_at)}[/] [dim]{_safe(record.id)}[/]")
    console.print(f"    [dim]{ending}[/]")
    console.print(f"  [bold]Source:[/] {_safe(record.source)} [dim](as the reader declares it)[/]")
    console.print(f"  [bold]Read for:[/] {_scope_phrase((record.use,))}")
    console.print(f"  [bold]Under grant:[/] {_read_grant_line(record)}")
    console.print(
        f"  [bold]Produced:[/] {record.produced} item(s) "
        "[dim](a count of what the source returned, never the thing itself)[/]"
    )
    console.print()


def _render_reads(recorded: tuple[SourceReadRecord, ...], *, limit: int) -> None:
    """The bounded listing, and the four things the page itself has to say.

    **Order is recording order, newest first, and is not the instant on the row**
    (ADR-0185 §6). The store keys its own prune on recording order precisely
    because ``checked_at`` is caller-supplied and can move backwards, so a page
    whose positions disagreed with its instants would be correct and would look
    broken. The footer says which of the two is the claim.

    **Liveness is not derivable from history** (ADR-0186 §8's first clause,
    ADR-0185 §8). A row states an attempt was made — never that the source is still
    allowed, that the grant it names still exists, or what the scope is now. That
    sentence is printed rather than assumed, because the reader who most needs it
    is the one treating this list as a permissions screen; ADR-0139 §6's clause
    runs the other way too, and nothing here puts a read beside a standing grant.

    **An empty page is not a claim that nothing was ever read.** ADR-0185 §7's
    argument for recording refusals is that an absence in a pruning store is
    ambiguous by construction — no row could mean not read, or pruned, or never
    recorded — so the one thing this surface must not do is turn an empty page into
    the statement the store declines to make. Both reasons are named rather than
    one: the horizon (§6), and ADR-0185 §5a's two fault paths, on which a read can
    run with no row — certainly so where the recorder raised, and *indeterminately*
    so where a cancellation landed inside a recorder call already in flight, which
    ADR-0060 forbids assuming either way. Neither path is licence to leave an
    access unrecorded — §5a forbids citing them as one — and both are why no line
    here says "every read".

    **The horizon is stated on the listing as well as on the export** (ADR-0186
    §10). A user who raises ``--limit`` until the page stops growing has reached the
    horizon and not the beginning, and a bound with no way to tell those apart is a
    truncation the reader cannot see.

    Args:
        recorded: The page, in the operation's order.
        limit: The bound that was asked for, so a full page can say it is one.
    """
    if not recorded:
        console.print("[yellow]Nothing recorded.[/] No attempt to read a source is in this record.")
        console.print(
            "[dim]That is not a claim that nothing was ever read: this record states "
            "what it holds, the oldest attempts are dropped as it fills, and a fault "
            "can leave a read with no row.[/]"
        )
        return
    console.print(f"[bold]{len(recorded)}[/] read attempt(s), newest recorded first:\n")
    for record in recorded:
        _render_read(record)
    if len(recorded) == limit:
        console.print(
            f"[dim]Showing {limit}. Ask for more with --limit; there is no total "
            "count, and 'assistant export-reads' writes every attempt still held.[/]"
        )
    console.print(
        "[dim]Each row is an attempt that was made. It does not say the source is "
        "still allowed, what you allow it for now, or that the grant named above "
        "still exists — 'assistant granted' is what states that.[/]"
    )
    console.print(
        "[dim]What a source returned is counted here and never shown: this record "
        "holds no content at all. And a row says what was attempted, not what came "
        "of it: what any use then did with a reading is a different record.[/]"
    )
    console.print(
        "[dim]The order is the order I recorded these in, newest first — not an "
        "ordering by the instant shown, which is when I checked whether you allowed "
        "the read. The oldest attempts are dropped as this record fills, so it "
        "reaches back only as far as it still holds.[/]"
    )


# --- rendering the connection surface (ADR-0151 §4, §5, §7, §8, §9) ----------


# --- rendering the invocation trail (ADR-0192 §4) ---------------------------
# The third pair's rendering, over the same store as the decision block above and
# a different row kind. What is inherited from ADR-0186 §7 is its last two
# clauses — a row is rendered whole or **fewer rows** are, and every value is
# inserted as data — and §8's bars on liveness, on authorisation and on event
# wording (ADR-0192 §4). What is added is this row kind's own floor and its own
# bars, and the bars are the harder half: what a row says is small and what a
# reader wants it to say is large.


def _recorded_at(instant: datetime) -> str:
    """The instant an invocation row was appended, at :func:`_decided_at`'s precision.

    **The same format for a different fact**, on :func:`_checked_at`'s reasoning:
    ADR-0192 §4 requires "the instant it was recorded" as part of the row and
    forbids a surface truncating any part of what it renders, so a minute-grained
    instant would be a truncation. This store makes the case stronger than either
    of the other two — a claim and the completion that names it are written either
    side of one tool call, typically milliseconds apart, so at ``%H:%M`` the pair
    renders as one instant twice and the ordering key disappears from the page.

    **It is not the durable append order** (ADR-0192 §2). The ledger decides every
    admission rule on its own append order precisely so a wall clock that steps
    backwards cannot make a completed act stop being the most recent one; this
    value is what the guarded clock read at the append and no more. It *is* the
    listing's primary sort key (§4), which is a different claim from being the
    ledger's order and is the only one this surface makes.

    A pure formatting of a value that arrived on the row — no clock is consulted
    here, and none may be (golden rule 3).
    """
    return _decided_at(instant)


def _invocation_kind(row: ToolInvocation) -> tuple[str, str]:
    """The row's kind — claim or completion — and what that kind states.

    **Every row states its kind** (ADR-0192 §4), because the two are different
    facts and a page holding both must render neither in the other's vocabulary.
    :attr:`~ai_assistant.core.types.ToolInvocation.completes` is the
    discriminator the model itself uses, so this branches on the same field the
    validator does rather than on a second spelling of it.

    **A claim is a call begun and never a call pending** (ADR-0192 §4). The words
    *pending*, *open*, *in flight*, *awaiting an outcome* and "has no completion
    yet" are all the same inference wearing different clothes: no row carries the
    fact, establishing it would need the join across two operations §4 forbids,
    and a completed call's claim row says nothing whatever about its completion.

    **It is not a statement that the tool callable was entered**, either (ADR-0192
    §4, ADR-0034 §1). The claim is written *before* the callable, and §1's
    cancellation clause has a path where the claim lands, a completion is written,
    and the callable is provably never entered — so what the row says is that this
    system spent an authorisation and attempted a call, which is what the sentence
    below says and the most a claim carries.

    Args:
        row: The invocation row, for its discriminator.

    Returns:
        The kind's word, coloured, and the sentence stating what the kind is.
    """
    if row.completes is None:
        return (
            "[cyan]call begun[/]",
            "a claim: I spent an authorisation and attempted a call. It does not say "
            "the tool itself was entered, and it says nothing about how the call ended",
        )
    return (
        "[blue]call finished[/]",
        "a completion: how an attempted call ended, written after it",
    )


def _invocation_outcome(outcome: ToolOutcome, *, egress_call: bool) -> tuple[str, str]:
    """How a completed call ended: the outcome's word, and what it does and does not say.

    **The word is the enum's own**, on :func:`_read_ending`'s reasoning: what a
    user sees on screen and what an exported row carries are the same three words,
    so a reader comparing a screen with an ``invocations.json`` needs no glossary.

    **``SUCCEEDED`` is the one state that establishes the callable was entered**
    (ADR-0192 §4). It is the tool reporting an outcome back through the seam, which
    is unreachable without it — and where the row also carries ``egress_call`` true
    this is the one place a surface may say the egress call was **attempted and
    reported success**. It says it on no other row and in no other state.

    **It may not say the call was *sent***, and the withholding is deliberate
    rather than fussy (ADR-0192 §4, ADR-0031 §4). ``SUCCEEDED`` is bounded to three
    facts — a validated callable return, an unexpired deadline, and no increase in
    the cancellation count — and none of them is a transmission; an egress callable
    that returns normally without putting a byte on the wire produces ``SUCCEEDED``
    like any other. Nothing available could carry the word either:
    ``ToolImplementation`` returns ``FrozenJson | ReportedOutput`` (ADR-0195 §2),
    and neither arm has a channel for a transmission fact — the envelope carries
    ``output`` and ``incurred_cost`` and, under ``extra="forbid"``, nothing else, so
    it states a price and never an outcome. And nothing here says or implies that
    anything was received, delivered or acted on by any recipient, on any row, in
    any state: ``SUCCEEDED`` is what the tool reported to the seam, and nothing in
    this system observes what happened after that — or upstream of it.

    **``INDETERMINATE`` is a state and not a hedge** (ADR-0014 §4, ADR-0192 §3).
    The call may or may not have taken effect, and a surface resolving that in
    either direction would be minting the fact the outcome exists to refuse.

    Total over the enum through :func:`~typing.assert_never`, so a fourth outcome
    would fail the type check rather than render as an empty ending.

    Args:
        outcome: How the call ended, as the row states it.
        egress_call: Whether the named decision carried an egress binding — read
            only to decide the one extra sentence ``SUCCEEDED`` licenses.

    Returns:
        The outcome's own word, coloured, and the sentence bounding what it states.
    """
    match outcome:
        case ToolOutcome.SUCCEEDED:
            if egress_call:
                return (
                    "[green]succeeded[/]",
                    "the tool reported success. This was an outbound call, and what "
                    "that states is that it was attempted and reported success — "
                    "no more than that",
                )
            return "[green]succeeded[/]", "the tool reported success"
        case ToolOutcome.FAILED:
            return "[red]failed[/]", "the tool reported that the call did not succeed"
        case ToolOutcome.INDETERMINATE:
            return (
                "[yellow]indeterminate[/]",
                "the tool could not say whether the call took effect, and I cannot "
                "resolve that in either direction",
            )
    assert_never(outcome)


def _invocation_failure_kind(row: ToolInvocation) -> str:
    """The kind the completion reported, or the statement that none was (ADR-0192 §4).

    Three shapes and each is stated rather than inferred. A ``SUCCEEDED``
    completion carries no kind by construction and this is not called for one. A
    completion carrying a kind renders **that kind exactly**, substituting nothing.
    A completion whose outcome is not ``SUCCEEDED`` and which carries **no** kind —
    the cancellation-derived completion ADR-0192 §2 permits and forbids any lane to
    fill — renders **that no kind was reported**.

    **That third shape is where a helpful surface goes wrong.** Rendering a kind of
    its own would be minting a fact the record declines to hold; rendering a blank
    would let the reader supply one; dropping the row or the field would hide that
    a call ended without a reported kind, which is itself information. It is
    ADR-0184's positively-read absence, one store over, and the same treatment this
    module already gives an unknown cost and an unrecorded origin.

    Args:
        row: The completion row.

    Returns:
        The reported kind, or the sentence naming the absence as one.
    """
    if row.failure_kind is not None:
        return f"{_safe(row.failure_kind.value)}"
    return "[dim]none was reported — the record holds no kind for this one[/]"


def _incurred_cost(cost: ToolCost) -> str:
    """What the invocation cost, as the tool reported it (ADR-0192 §4, §5).

    **Three bases, and ``UNKNOWN`` is the one the floor is written for.** ADR-0192
    §4 requires the incurred cost on every completion "**including that the cost is
    unknown** where the basis is ``UNKNOWN``", so the absence is stated as a state
    rather than shown as a blank, a zero or a dash. *Free* and *unknown* are the
    distinction :class:`~ai_assistant.core.types.ToolCost` exists to keep apart —
    the first is a fact a running total can add, the second an absence a ceiling
    must fail closed on (ADR-0016 §4) — and a surface folding them would undo at
    the last inch what the type protects everywhere else.

    **It is what the tool reported and never what the definition advertised**
    (ADR-0192 §2, §5). ``ToolDefinition.cost`` is a price list; this is what this
    invocation incurred, and the two are different facts even when the numbers
    agree.

    Total over the enum through :func:`~typing.assert_never`.

    Args:
        cost: The cost the completion carries.

    Returns:
        The amount with its currency, or the sentence naming which absence this is.
    """
    match cost.basis:
        case CostBasis.PER_CALL:
            # Both members are present on this basis by construction
            # (``ToolCost._amount_matches_basis``), so neither branch below is
            # reachable with one missing.
            return f"{_safe(str(cost.amount))} {_safe(str(cost.currency))}"
        case CostBasis.FREE:
            return "free [dim](the tool reported this invocation carried no charge)[/]"
        case CostBasis.UNKNOWN:
            return (
                "[yellow]not known[/] [dim](the tool reported no cost for this "
                "invocation; that is not the same as free)[/]"
            )
    assert_never(cost.basis)


def _render_invocation(recorded: RecordedInvocation) -> None:
    """One invocation row, whole (ADR-0192 §4).

    **The floor, field by field.** Every row renders its kind, the instant it was
    recorded, and the tool identifier and capability *the value itself carries* —
    from the join the store made, never from a registry and never from a second
    call. A completion also renders the outcome, the failure kind where the row
    carries one or the statement that none was reported, and the incurred cost
    including that it is unknown. Nothing is omitted, truncated, summarised,
    sampled or counted in place of, so a narrow terminal gets fewer rows rather
    than shorter ones.

    **Every value comes from the row in hand** (ADR-0192 §4). Nothing here joins
    two operations' answers, reads a store, calls a second operation to complete a
    row, or infers a missing half — which is what the store-side join exists to
    make unnecessary, and what golden rule 3 would forbid this layer doing anyway.

    **No recipient, account, endpoint or destination is named, on any row, in any
    state** (ADR-0192 §4). ``egress_call`` states that the call was an outbound one
    and states nothing about whose bytes went where; who a ruling was taken over is
    ``assistant decisions``' to render from the binding itself, under ADR-0186 §7's
    floor. The row carries none of it to render even if this wanted to (ADR-0192
    §2).

    **The authorisation is named and never resolved here.** ``decision_id`` points
    one way, at a row ``assistant decisions`` renders; this prints it as recorded,
    looks nothing up, and claims nothing about what that ruling now says — the
    pointer treatment :func:`_read_grant_line` already gives a grant id, and
    ADR-0186 §8's liveness bar read one row kind over.

    Every value is inserted as data and neutralised for this terminal (ADR-0192
    §4's last clause, ADR-0042 §4). Being read from an append-only store relaxes
    nothing: a tool identifier and a capability are values a registration supplied,
    and ``VisibleIdentifier`` admits far more than this terminal treats as inert.
    """
    row = recorded.invocation
    kind, states = _invocation_kind(row)
    console.print(f"  {kind} [dim]{_recorded_at(row.recorded_at)}[/] [dim]{_safe(row.id)}[/]")
    console.print(f"    [dim]{states}[/]")
    console.print(
        f"  [bold]Tool:[/] {_safe(recorded.tool)} [dim](capability {_safe(recorded.capability)})[/]"
    )
    console.print(
        f"  [bold]Outbound call:[/] {'yes' if recorded.egress_call else 'no'} "
        "[dim](whether the ruling this row names carried an outbound binding; "
        "who or where is not on this row)[/]"
    )
    console.print(
        f"  [bold]Under authorisation:[/] {_safe(row.decision_id)} "
        "[dim](what it cited then; it is not looked up now)[/]"
    )
    if row.outcome is not None:
        word, ending = _invocation_outcome(row.outcome, egress_call=recorded.egress_call)
        console.print(f"  [bold]Ended:[/] {word} [dim]— {ending}[/]")
        if row.outcome is not ToolOutcome.SUCCEEDED:
            console.print(f"  [bold]Failure kind:[/] {_invocation_failure_kind(row)}")
        # A completion always carries one; the model refuses one without
        # (``ToolInvocation._is_a_claim_or_a_completion``).
        if row.incurred_cost is not None:
            console.print(f"  [bold]Cost:[/] {_incurred_cost(row.incurred_cost)}")
    console.print()


#: How each :class:`~ai_assistant.core.types.SpendPeriod` is named on the page. A
#: table rather than a ``.replace("_", " ").title()``, so a member added later is a
#: ``KeyError`` at the one place that has to choose a word rather than a machine
#: spelling silently reaching a user.
#: Spelled once and used by the two spend-boundary helpers below, so neither carries
#: a bare literal a reader has to recognise.
_SECONDS_A_DAY: Final = 86_400
_MICROS_A_SECOND: Final = 1_000_000

_PERIOD_NAMES: Final[Mapping[SpendPeriod, str]] = {
    SpendPeriod.CALENDAR_DAY: "Today",
    SpendPeriod.CALENDAR_MONTH: "This month",
}


def _offset_label(offset: timedelta) -> str:
    """Spell a UTC offset as ``+HH:MM``, or ``+HH:MM:SS`` where seconds are in force.

    **Seconds are shown when the zone database carries them and not otherwise**
    (ADR-0194 §5). ``Asia/Manila``'s ``-15:56:08`` and ``America/Metlakatla``'s
    ``+15:13:42`` are real historical offsets a ``SpendTotal`` may carry, and a
    renderer rounding to the minute would print an offset the clock contract says
    was never in force. A whole-minute offset — every modern one — keeps the short
    form, because a trailing ``:00`` on every line teaches a reader nothing.

    **A sub-second offset keeps its fraction, and so does a sub-second bound.**
    :class:`~ai_assistant.core.types.SpendTotal`'s own validator admits an offset "at
    whatever resolution it has", and its cross-field rule exists so that "a renderer
    performs exactly those two additions" — which is a claim that the rendering is
    total over what the type accepts. Reading the offset through
    ``total_seconds()`` truncated one: ``timedelta(microseconds=-500_000)`` came out
    ``+00:00``, sign and all. No zone database carries such an offset, so this is a
    value nothing produces today; what makes it worth closing is that the
    truncation is silent and its direction is wrong — it states a boundary the
    ledger did not use rather than declining to state one.
    """
    micros = (
        offset.days * _SECONDS_A_DAY + offset.seconds
    ) * _MICROS_A_SECOND + offset.microseconds
    sign = "-" if micros < 0 else "+"
    seconds, fraction = divmod(abs(micros), _MICROS_A_SECOND)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    stem = f"{sign}{hours:02d}:{minutes:02d}"
    if not seconds and not fraction:
        return stem
    stem = f"{stem}:{seconds:02d}"
    return stem if not fraction else f"{stem}.{fraction:06d}"


def _bound(instant: datetime, offset: timedelta) -> str:
    """Render one period boundary from **its own** offset (ADR-0194 §5, §6).

    The value carries the offsets its producer resolved as in force at its two
    instants, so this adds one to the other and labels the result. It resolves no
    zone, reads no ``tzdata``, consults no configuration of this process's and reads
    no clock — which is what lets a client on a different zone database render a
    figure a hub computed correctly, and is golden rule 3 besides.

    **Both offsets are carried and both are used**, because a period containing a
    transition has different offsets at its two ends — the case ADR-0194 §1's
    boundary rule exists for, and the one a single offset would misrender.

    **A fraction of a second survives, from either side of the addition.** The
    instant is a ``UtcInstant`` and may carry microseconds, and so may the offset, so
    a fixed ``%H:%M:%S`` states a boundary a microsecond off the one the ledger used.
    A whole-second boundary — every one a zone database produces — keeps the short
    form, for :func:`_offset_label`'s reason.
    """
    shifted = instant.replace(tzinfo=None) + offset
    stamp = shifted.strftime("%Y-%m-%d %H:%M:%S")
    return stamp if not shifted.microsecond else f"{stamp}.{shifted.microsecond:06d}"


def _render_spend(totals: tuple[SpendTotal, ...]) -> None:
    """Both period totals, in the ledger's order, and the four sentences §6 owes.

    **An absence is stated as the state it is**, and ``currency`` is what tells the
    two apart (ADR-0194 §5, §6). ``currency=None`` means no currency is configured
    and no total was computed; a present ``currency`` beside ``accounted=None``
    means the period could not be measured. A renderer collapsing them into one
    message tells a user "no total" while their calls are being refused.

    **The consequence line is printed from that period's own ceiling and never from
    the absence of a total.** ADR-0194 §2 refuses nothing on an indeterminate period
    the user set no ceiling for, so a renderer keying on ``accounted is None`` alone
    tells a user their calls are blocked when they are not.

    **Nothing here reads falsiness of a ceiling.** A configured ceiling of zero is
    the configuration that refuses the most, so it is exactly the one where "no
    ceiling" would be furthest from the truth.

    **No total is presented as an amount billed, owed or charged** (ADR-0194 §6). It
    is the sum of what this system's own tools reported, and the footer says so.
    """
    for total in totals:
        name = _PERIOD_NAMES[total.period]
        opened = (
            f"{_bound(total.period_start, total.start_offset)} {_offset_label(total.start_offset)}"
        )
        closed = f"{_bound(total.period_end, total.end_offset)} {_offset_label(total.end_offset)}"
        console.print(f"[bold]{name}[/]")
        console.print(f"  [dim]from {opened}[/]")
        console.print(f"  [dim]up to (not including) {closed}[/]")
        if total.currency is None:
            console.print("  [dim]No spend currency is configured, so I am not keeping a total.[/]")
        elif total.accounted is None:
            console.print(
                f"  [yellow]Not measurable.[/] Something in this period has no price I may "
                f"add — a call still in flight, or one whose cost nobody reported — so I "
                f"will not state a {total.currency} figure I would be inventing."
            )
            if total.ceiling is not None:
                console.print(
                    f"  [red]Nothing further will run in this period[/] while that is so: "
                    f"there is a ceiling of {total.ceiling} {total.currency} here and I "
                    f"cannot tell whether a call would cross it."
                )
            else:
                console.print(
                    "  [dim]Nothing is being refused on that account: you have set no "
                    "ceiling for this period.[/]"
                )
        else:
            stated = f"  [bold]{total.accounted} {total.currency}[/]"
            if total.ceiling is None:
                console.print(f"{stated} [dim]— no ceiling set for this period.[/]")
            else:
                console.print(f"{stated} [dim]of a ceiling of[/] {total.ceiling} {total.currency}")
        console.print()
    console.print(
        "[dim]These are the prices my own tools reported for the calls I made. They are "
        "not a bill, not an amount owed, and not checked against anyone's statement.[/]"
    )


def _render_invocations(recorded: tuple[RecordedInvocation, ...], *, limit: int) -> None:
    """The bounded listing, and the four things the page itself has to say.

    **One attempt is up to two rows, and they are presented as the two rows they
    are** (ADR-0192 §4). Nothing here pairs them, counts them as one, or renders
    either in the other's vocabulary — and the footer says so, because a reader
    seeing "call begun" without "call finished" beneath it will otherwise supply
    the pairing themselves.

    **A page's silence is a fact about the page** (ADR-0192 §4). The absence of a
    completion, or of a claim, from a bounded page says something about the bound
    and nothing about the call: the other half may simply be further back. No count
    of calls, attempted or completed, is derived from anything but the rows on
    screen.

    **Liveness is not derivable from history** (ADR-0186 §8's first clause, read
    one row kind over). A row states that an act was recorded — never that the
    authorisation it names still stands, that the tool is still registered under
    the identifier printed, or that anything is still running.

    **An empty page is not a claim that nothing was ever attempted.** ADR-0192 §1's
    cancellation clause and §3's commit-state clause both admit paths where an
    attempt leaves fewer rows than a reader expects, so the one thing this surface
    must not do is turn an empty page into a statement the record declines to make.

    Args:
        recorded: The page, in the operation's order.
        limit: The bound that was asked for, so a full page can say it is one.
    """
    if not recorded:
        console.print("[yellow]Nothing recorded.[/] No act on an authorisation is in this record.")
        console.print(
            "[dim]That is not a claim that nothing was ever attempted: this record "
            "states what it holds, and a fault can leave an act with fewer rows than "
            "it made.[/]"
        )
        return
    console.print(f"[bold]{len(recorded)}[/] row(s), newest recorded first:\n")
    for row in recorded:
        _render_invocation(row)
    if len(recorded) == limit:
        console.print(
            f"[dim]Showing {limit}. Ask for more with --limit; there is no total "
            "count, and 'assistant export-invocations' writes the whole record.[/]"
        )
    console.print(
        "[dim]One attempt is up to two rows — a call begun, and how a call finished. "
        "They are two rows and not one, and a row with no partner on this page is a "
        "fact about the page: the other half may be further back.[/]"
    )
    console.print(
        "[dim]A row says I spent an authorisation and attempted a call. It does not "
        "say the authorisation still stands, that the tool is still registered under "
        "the identifier above, or that anything is still running.[/]"
    )
    console.print(
        "[dim]Nothing here names who or where an outbound call went, and nothing "
        "here says what became of it at the other end — I do not observe that. "
        "'assistant decisions' is where a ruling's outbound binding is shown.[/]"
    )


def _reference_hint(reference: str, command: str, *, subject: str = "That reference") -> str:
    """One copyable command naming a reference, or the line that replaces it.

    :func:`_argument` and :func:`_is_pasteable` composed the way every other hint on
    this surface composes them (#984, #1013). A minted reference is bounded and
    chosen by code, but nothing in :data:`~ai_assistant.core.types.DurableIdentifier`
    forbids a byte a terminal must not be handed — and a *wrong* command is worse
    than no command, because it is a working instruction naming something else.

    Args:
        reference: The reference as the hub returned it.
        command: The command to build, e.g. ``"assistant disconnect"``.
        subject: What cannot be shown, opening the replacement sentence.

    Returns:
        The text to print, quoted or withheld.
    """
    if not _is_pasteable(reference):
        return _uncopyable(subject, "The command still takes it, given the exact bytes.")
    # The trailing period is inside the hint rather than at each call site, so the two
    # branches are interchangeable in a sentence: ``_uncopyable`` returns a finished
    # sentence, and a caller appending its own punctuation would double it there.
    return f"'{command} {_argument(reference)}'."


def _connection_state_phrase(state: ProvisioningState) -> str:
    """Say what one record's provisioning state means, in words (ADR-0151 §4).

    **The pending phrasing is a normative clause rather than a wording choice.**
    ADR-0151 §4 requires a surface rendering a ``PENDING`` record to say the
    reference is *not connectable* and that the remedy is to run the act again, and
    forbids saying that the connection is being established, is in progress, or will
    complete on its own. Nothing is running: ADR-0148 §6 rules an interrupted act's
    state "refused rather than reconciled", the act that wrote the record is gone,
    and the record is inert until a person acts.

    Total over the enum through :func:`~typing.assert_never`, so a third member
    would fail the type check rather than render as an empty string.
    """
    match state:
        case ProvisioningState.ACTIVE:
            return "connected"
        case ProvisioningState.PENDING:
            return "not connectable — the act that wrote it never finished"
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(state)


def _render_connection_intent(identity: str, *, reference: str | None = None) -> None:
    """Show the account identity before the credential is asked for (ADR-0151 §5).

    "No surface accepts an identity it does not display" is §5's own sentence, and
    the hub cannot enforce it — nothing on the wire distinguishes a client that
    rendered the value (ADR-0098 §5). What it buys is ADR-0149 §4's third answer to
    a credential typed into the name field: the value is *seen*, by the one person
    who can tell that it is the wrong value.

    The identity is rendered and never echoed anywhere else — it is Tier 1 personal
    data, so it reaches no log line and no error message (ADR-0149 §3).
    """
    where = "" if reference is None else f" under [bold]{_safe(reference)}[/]"
    console.print(f"About to connect the account [bold cyan]{_safe(identity)}[/]{where}.\n")
    console.print(
        "[dim]That is the name I will record and show you, exactly as you typed it — "
        "I normalise nothing. If it is not the account you meant, or if it is your "
        "credential, stop here.[/]\n"
    )


def _render_unusable_credential(exc: ValueError) -> None:
    """Report a credential this surface will not carry, having sent nothing.

    The message is :func:`~ai_assistant.core.types.secret_value`'s own, and it is
    safe to print for a reason worth stating: ADR-0125 §6 forbids any exception that
    seam raises from carrying a prefix, a suffix, a truncation, a digest **or a
    length** of the rejected value. So it says which rule was broken and nothing
    about what broke it.
    """
    console.print(f"[red]That credential cannot be used:[/] {_safe(str(exc))}. Nothing was sent.")


def _render_connected(verb: str, record: ConnectedAccount) -> None:
    """Report a completed provisioning act, with the reference the hub minted.

    An act returns only once ADR-0148 §6's **third** write has landed, so this is
    the one place on the surface where a connection may be called live — and the
    record carries ``ACTIVE`` by contract (ADR-0151 §7).

    The reference is printed prominently because it is the whole handle: §3 minted
    it inside the act, the user did not choose it, and every act after this one is
    performed against a value they read back off a listing.
    """
    console.print(
        f"[green]{verb}.[/] [bold cyan]{_safe(record.identity)}[/] is connected, "
        f"at revision {record.revision}."
    )
    console.print(f"  Its reference is [bold]{_safe(record.reference)}[/]")
    _print_hint(
        "  [dim]Read it back any time with 'assistant connections'. Replace its "
        "credential with 'assistant reconnect', or end it with "
        f"{_reference_hint(record.reference, 'assistant disconnect')}[/]"
    )
    console.print(
        "\n[dim]This is a connection, not a permission: it authorises nothing on its "
        "own. What I am allowed to read is 'assistant granted'.[/]"
    )


def _render_cancelled_act(act: str) -> None:
    """Say a cancelled act's outcome is not known, starting no call (ADR-0151 §7).

    §7's cancellation clause has three parts and the middle one is load-bearing: a
    cancelled client is still asked to report, which invites reading the state
    before reporting it — the same breach by a kinder route. So this says what
    happened to the act, and the caller says the state is unread without asking. The
    ``CancelledError`` then leaves unconverted, which ADR-0060 requires and which no
    report satisfies.
    """
    console.print(
        f"[yellow]The outcome of the {act} is not known.[/] It was cancelled, and a "
        "cancelled act leaves exactly the states a lost answer does — it may have "
        "been done anyway."
    )


def _render_unknown_outcome(act: str, exc: Exception) -> None:
    """Report an act whose outcome cannot be asserted in either direction.

    Three failures land here and each is genuinely unknown rather than merely
    unreported. A :class:`~ai_assistant.core.errors.ConnectionStoreError` is raised
    *before the act's own first write returns*, so whether that write landed cannot
    be asserted and a reference may or may not exist (ADR-0151 §7). A
    ``TransportError`` is the answer having been lost after the hub may already have
    committed (ADR-0084 §3). And an
    :class:`~ai_assistant.core.errors.OversizedValueError` is a *typed* refusal that
    is nonetheless unknown, for :func:`_outcome_of`'s reason: on a mutating call the
    result is measured after the work has committed (ADR-0085 §8e, #570), so an
    oversized result means the act landed and could not be reported — while an
    oversized argument is refused before any I/O. A caller cannot tell those apart.
    """
    remedy = (
        " The frame this hub is configured with is too small to carry it; raising "
        "'hub_max_frame_bytes' is the operator's remedy."
        if isinstance(exc, OversizedValueError)
        else ""
    )
    console.print(
        f"[yellow]The outcome of the {act} is not known.[/] "
        f"{_safe('; '.join(_leaf_messages(exc)))}.{remedy} I am not saying it landed "
        "and I am not saying it did not."
    )


def _render_provisioning_outcome(act: str, exc: Exception, *, reference: str | None) -> None:
    """Say what one failed provisioning act is known to have done (ADR-0151 §7).

    Six outcomes, six sentences and six next steps, and no two of them
    interchangeable — a surface that collapsed any pair would tell a person their
    credential was unused when it was live, or send them to re-run an act that had
    already worked. The vocabulary is ADR-0139 §4's ("landed", "known not to have
    landed", "not known"), which ADR-0151 §7 transposes from an amendment's two
    calls to one act's three writes.

    Two negatives are as load-bearing as the positives. An
    :class:`~ai_assistant.core.errors.IncompleteProvisioningError` is **never**
    reported as the call having changed nothing — its own first write landed, and
    the reference it names exists. And a
    :class:`~ai_assistant.core.errors.DisplacedProvisioningError` is **never**
    reported as having left the store unchanged, as having rolled anything back, or
    as a reason to retry the same act blind: ADR-0148 §6 displaces an act that may
    already have appended its entry and written its credential.
    """
    named = "that reference" if reference is None else f"[bold]{_safe(reference)}[/]"
    match exc:
        case UnusableIdentityError():
            console.print(
                f"[red]The {act} is known not to have landed[/] — I refused the "
                f"account name before anything was sent, so your credential never "
                f"left this machine: {_safe(str(exc))}."
            )
        case UnknownConnectionError():
            console.print(
                f"[red]The {act} is known not to have landed[/] — I hold no "
                f"connection under {named}, so nothing was written. "
                "'assistant connections' lists the references I do hold."
            )
        case DisplacedProvisioningError():
            console.print(
                f"[red]The {act} was not performed.[/] Another act took {named} over "
                "while this one was running, so no record I wrote is that "
                "reference's live one. Nothing was rolled back, and this act may "
                "have left an entry and a credential of its own that no call reads — "
                "disconnecting that reference removes them. Do not simply run it "
                "again; read what is connected first."
            )
        case IncompleteProvisioningError():
            console.print(
                f"[yellow]The {act} did not complete.[/] The reference {named} "
                "[bold]exists[/] — I wrote its record — and the credential you gave me "
                "was never put into use, so it will not become the live one. This "
                "call did not leave things as they were. Run the act again on that "
                "reference, or disconnect it; both are safe."
            )
        case ProvisioningOutcomeUnknownError():
            console.print(
                f"[yellow]The outcome of the {act} is not known.[/] The reference "
                f"{named} [bold]exists[/]; whether the credential you gave me is now "
                "in use I cannot say, because the store may have committed and failed "
                "before telling me. [bold]Do not run it again on the assumption it "
                "failed[/] — that would replace a credential that may already be "
                "working."
            )
        case ResidualCredentialError():
            _render_residual_credential(
                f"The {act} completed, and the connection is live at its new revision.",
                exc,
                reference=reference,
            )
        case _:
            _render_unknown_outcome(act, exc)


def _render_residual_credential(landed: str, exc: Exception, *, reference: str | None) -> None:
    """Report an act that **completed** and whose credential deletion did not.

    ADR-0151 §7 and §8 both state what a caller may conclude, and both state it as a
    prohibition first: no client reports this as a failed connection or a failed
    disconnection. The act landed. What did not is the removal of a credential the
    act was to delete — a predecessor's slot, or the disconnection's own pass — so an
    unreferenced credential remains, named by the store, read by no call, and
    reachable by running the disconnection again.

    It is raised rather than reported in a field for ADR-0149 §5's reason: the
    failure "is reported and never suppressed", and a boolean is precisely what an
    inattentive client suppresses by rendering the success and dropping the flag.
    """
    where = "" if reference is None else f" for [bold]{_safe(reference)}[/]"
    console.print(f"[green]{landed}[/]")
    console.print(
        f"[yellow]A credential I was to delete{where} is still there:[/] "
        f"{_safe('; '.join(_leaf_messages(exc)))}. Nothing reads it and no live "
        "record names it, but it has not gone."
    )
    if reference is not None:
        _print_hint(
            f"  [dim]Run {_reference_hint(reference, 'assistant disconnect')} again to "
            "finish the deletion — it is safe to repeat.[/]"
        )


def _render_connections_unread() -> None:
    """Say nothing is known about what was written, with no reference to name.

    The state a ``connect_account`` failure before the first write leaves: there may
    or may not be a record, and there is certainly no handle, because ADR-0151 §3
    mints one only as that first record is written. ADR-0151 §7 resolves it by a
    read of ``connected_accounts`` **once the store is readable**, which is a later
    command rather than a second call now.
    """
    console.print(
        "[dim]I have not read what is connected, and there is no reference to name. "
        "'assistant connections' will tell you, once the hub can answer.[/]"
    )


def _render_connection_unread(reference: str) -> None:
    """Say one reference's state is unread, and start no call to find out.

    ADR-0151 §7's cancellation clause: "A cancelled client starts no new call in
    order to report". ADR-0060 permits deferring a cancellation only while a method
    makes its resources safe, and a read performed to present a state is not that —
    so this says the state is unread, starts nothing, and lets the
    ``CancelledError`` leave.
    """
    console.print(
        f"[dim]I have not read the state of {_safe(reference)}, so I am not saying. "
        "'assistant connections' will tell you.[/]"
    )


def _render_connection_state(reference: str, state: ConnectedAccount | None | _Unread) -> None:
    """State one reference's live record, from a read and never from an act's outcome.

    ADR-0151 §7's resolution, and :func:`_render_state`'s shape one surface over.
    Three answers, and the middle one is the one an author collapses: a ``None`` is
    "I read the store and it holds no live record for this reference", which is
    **not** the same as "the reference does not exist" — the store may hold entries
    for it that no live record names (ADR-0149 §3, §5).
    """
    if isinstance(state, _Unread):
        console.print(
            f"[dim]I could not read the state of {_safe(reference)}, so I am not "
            "saying. Try 'assistant connections'.[/]"
        )
        return
    if state is None:
        console.print(
            f"I read the store: nothing is connected under [bold]{_safe(reference)}[/] right now."
        )
        return
    console.print(
        f"I read the store: [bold]{_safe(reference)}[/] holds "
        f"[bold cyan]{_safe(state.identity)}[/] at revision {state.revision}, "
        f"{_connection_state_phrase(state.state)}."
    )


def _render_connections(connected: tuple[ConnectedAccount, ...]) -> None:
    """Render what is connected now, whole, with each record's state (ADR-0151 §4, §9).

    **The set is presented as it arrived.** No record is dropped because no
    integration is built for it, nothing is merged in from the act history, and no
    state is re-derived — a connection the hub can do nothing with is exactly what
    this command exists to show, and each of those moves would hide it from the
    disconnection that is its owner's only remedy (ADR-0139 §1, ADR-0151 §9).

    **A ``PENDING`` row is visibly not a working connection**, which is the clause
    ADR-0151 §4 puts on a client and #1130 filed against the delete act's own
    statement of the same list. It says the reference is not connectable and what
    the remedy is, and it never says the connection is being established or will
    complete on its own.

    **A listing says which account and not which service**, and that is a
    consequence rather than an omission: nothing in the tree says what an
    integration *is* yet, so there is nothing honest to put there (ADR-0151 §18).
    """
    if not connected:
        console.print(
            "[yellow]Nothing is connected.[/] 'assistant connect' adds an account; "
            "it is a different question from 'assistant granted', which is what I am "
            "allowed to read."
        )
        return
    console.print(f"[bold]{len(connected)}[/] connection(s):\n")
    for record in connected:
        console.print(f"  [bold cyan]{_safe(record.identity)}[/]")
        console.print(f"    [dim]{_safe(record.reference)}[/] — revision {record.revision}")
        if record.state is ProvisioningState.ACTIVE:
            console.print(f"    [green]{_connection_state_phrase(record.state)}[/]")
        else:
            console.print(f"    [yellow]{_connection_state_phrase(record.state)}[/]")
            console.print(
                "    [yellow]Nothing is in progress and nothing will finish it.[/] "
                "Run the act again with 'assistant reconnect', or end it below."
            )
        _print_hint(
            f"    [dim]end it with {_reference_hint(record.reference, 'assistant disconnect')}[/]"
        )
        console.print()
    console.print(
        "[dim]This is a snapshot taken when you asked, not a claim that stays true. "
        "It says nothing about what I am permitted to do — a connection is not an "
        "authorisation; see 'assistant granted' — and it carries no times.[/]"
    )


def _render_connection_acts(acts: tuple[ConnectionAct, ...], *, limit: int) -> None:
    """Render what was done to connections, without claiming any of it is live.

    **An act is shown as an act and never as a standing** (ADR-0151 §9). The reason
    is not the clock one :func:`_render_grants` carries — there is no clock here at
    all — but the page boundary: this listing is bounded by ``limit``, so a
    reference whose latest act falls outside the page is one a client walking the
    page would report by an *earlier* act. That failure appears on the deployment
    with the most history and nowhere else, which is why the rule is stated over the
    shape rather than left to a reader's judgement.

    **A removal is the absence of the account and not a third state** (ADR-0149 §5),
    which is what this renderer's two branches are.

    **No position on this page means a time.** A connection record carries no
    instant, so the order is the order the store recorded the acts in and nothing
    more (ADR-0151 §4, §9).
    """
    if not acts:
        console.print("[yellow]Nothing recorded.[/] No connection has been made or ended.")
        return
    console.print(f"[bold]{len(acts)}[/] act(s), in the order I recorded them, newest first:\n")
    for act in acts:
        if act.account is None:
            console.print(f"  [bold]disconnected[/] [dim]{_safe(act.reference)}[/]")
        elif act.account.state is ProvisioningState.ACTIVE:
            console.print(
                f"  [bold]connected[/] [bold cyan]{_safe(act.account.identity)}[/] "
                f"[dim]{_safe(act.reference)}[/]"
            )
        else:
            # A row is what an act *reached*, never what a reference is now
            # (ADR-0151 §9), and "connected" over an act that never activated would
            # be that claim in one word. What the state says here is how far this
            # act got, which is the whole of what the row carries.
            console.print(
                f"  [bold]tried to connect[/] [bold cyan]{_safe(act.account.identity)}[/] "
                f"[dim]{_safe(act.reference)}[/] — [yellow]the act never completed[/]"
            )
        console.print(f"    [dim]revision {act.revision}[/]")
    if len(acts) == limit:
        console.print(
            f"\n[dim]Showing {limit}. Ask for more with --limit; there is no total count.[/]"
        )
    console.print(
        "\n[dim]There are no times here: a position is where I recorded the act and "
        "nothing else. What is connected [bold]now[/] is 'assistant connections' — a "
        "row here says an act happened, not that it still stands.[/]"
    )


def _render_disconnected(record: ConnectedAccount) -> None:
    """Report the live record a disconnection removed, and never more (ADR-0151 §8).

    The overclaim this wording exists to avoid is the sibling of ``revoke``'s
    (ADR-0102 §9): "that account can no longer be used" is the sentence a person
    writes, and it promises three things ADR-0149 §5 declines to. A disconnection
    does not stop a transmission already in flight, does not cancel a provisioning
    act that is running, and is not a guarantee that the keyring holds nothing for
    that reference. What is true is the weaker thing §5 does state — no live record
    names any slot for it.

    The last line closes an overclaim the acts make available *together*: a user who
    disconnects everything has not performed ADR-0149 §8's purge and has not
    discharged their delete right, and presenting it as either would be a purge that
    skips a scope arriving by composition instead of by omission.
    """
    console.print(
        f"[green]Disconnected.[/] [bold cyan]{_safe(record.identity)}[/] was live at "
        f"revision {record.revision}; no live record names any credential for "
        f"[bold]{_safe(record.reference)}[/] any more."
    )
    console.print(
        "[dim]That is the whole of what I can promise: it does not stop anything "
        "already in flight, it does not cancel an act that is running, and it is not "
        "a guarantee that my keyring holds nothing at all for that reference. "
        "Disconnecting everything is not the same as erasing this installation.[/]"
    )


def _render_nothing_removed(reference: str) -> None:
    """Report that no live record was removed, and say only that (ADR-0151 §8).

    A ``None`` is **not** a report of a disconnection, not a confirmation that a
    credential was deleted, and not a statement that the reference does not exist —
    the store may hold entries for it that no live record names, and the reference
    may simply never have been one of mine. All three of those are readings this
    wording has to refuse at once, which is why it says the one true thing and then
    points at the command that answers the question the user probably has.
    """
    console.print(
        f"[yellow]Nothing was removed:[/] no live record for "
        f"[bold]{_safe(reference)}[/] when the call ran. That is not a "
        "disconnection, and it does not say the reference is unknown to me — "
        "'assistant connections' says what is connected."
    )


def _render_error(exc: Exception, *, to_stderr: bool = False) -> None:
    """Render an error for the terminal, without leaking a traceback.

    Accepts any ``Exception`` — an :class:`AssistantError` the hub declined a
    request with, a :class:`~ai_assistant.wire.errors.TransportError` from the
    connection itself, or an exception group — and shows the actual cause. For a
    group that means the **contained** messages (recursively), not just the group's
    summary, so an operator sees *which* part failed, not merely that one did.

    **A transport failure is rendered as its own thing**, and that difference is
    ADR-0084 §3's rather than a presentation choice: "a connection-level close is a
    **transport** failure, which is not the same event as a request the hub
    received and declined, and ruling 4's legibility is the reason the difference
    survives to the user rather than being flattened into one message". A user who
    reads "Error:" for a hub that is not running looks for a fault in their
    request; the hub simply is not there.

    **The stream is a parameter because one command's standard output is an
    artifact** (ADR-0186 §9). ``export-decisions`` writes one JSON document and
    "nothing else on that stream", so its failures are the one case on this surface
    where an error message on standard output would corrupt the answer rather than
    explain it. Every other caller takes the default and writes where it always did.

    Args:
        exc: The failure to report.
        to_stderr: Whether to write to standard error instead of standard output.
            Set by the export path alone.
    """
    target = error_console if to_stderr else console
    if isinstance(exc, TransportError):
        target.print(f"[red]The assistant hub is not reachable:[/] {_safe(str(exc))}")
        return
    target.print(f"[red]Error:[/] {_safe('; '.join(_leaf_messages(exc)))}")


def _leaf_messages(exc: BaseException) -> list[str]:
    """The messages of ``exc``, flattening a (possibly nested) exception group."""
    if isinstance(exc, BaseExceptionGroup):
        return [message for sub in exc.exceptions for message in _leaf_messages(sub)]
    return [str(exc)]


if __name__ == "__main__":
    app()

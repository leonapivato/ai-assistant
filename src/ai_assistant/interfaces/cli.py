"""Command-line interface — the first adapter onto the engine (ADR-0042 §7).

Kept intentionally thin (golden rule 3, ADR-0042 §6): it parses input, obtains the
façade from the composition root, relays each command to the engine, renders what comes
back with Rich, and closes the façade on exit. Talking to the assistant is ``assistant
chat`` (ADR-0293, ADR-0309 §5:4). It authors no permission ruling, plans nothing,
selects no tool, and touches no subsystem directly — all of that is the engine's,
reached only through the façade (ADR-0042 §6). Registered as the ``assistant`` console
script in ``pyproject.toml``.

``beliefs`` and ``forget`` are the belief-inspection surface (ADR-0073 §7): they
render what the engine already computed and destroy what the user names. The
standing, the band and every value ADR-0328 §7 computes arrive on the DTO —
:class:`~ai_assistant.core.types.Belief` is projected in ``core`` so no standing is
computed here — and this module reads no clock for them and re-filters nothing. The
same holds for the supports (ADR-0328 §15:2, §15:7): each arrives already resolved
to readable content or shown as gone, so nothing here resolves a part or ever sees
an id it could pass off as a warrant.

``conversations`` and ``forget-conversation`` are the conversation surface
(ADR-0074 §2, §8, §10), and ``chat --conversation`` is how one is continued
(ADR-0293). A conversation the user deleted reaches none of these —
not because anything here filters it, but because the store hides a stamped
conversation from every read that presents one.

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
type — so what the adapter supplies is the reading and nothing more. It answers
expiry and nothing else: dismissal and a ``DROP`` are stamped by the hub and are
taken as final. On a remote hub the reading is this device's, so a record within
clock skew of its expiry may be labelled from the wrong side; that moves a label
and never a verb, the engine staying the authority on what any act does.

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
(ADR-0186 §8): nothing here composes a confirmation, offers an approval control,
computes ``authorises``, or says a call went anywhere.

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
import re
import shlex
import sys
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Final, NamedTuple, TextIO, assert_never, final

import typer
from pydantic import SecretStr
from rich.console import Console
from rich.markup import escape
from rich.text import Text

from ai_assistant import __version__
from ai_assistant.core.config import load_settings
from ai_assistant.core.episode_encoding import check_detail as check_episode_detail
from ai_assistant.core.episode_encoding import check_list as check_episode_list
from ai_assistant.core.errors import (
    AssistantError,
    ConfigurationError,
    DeviceRefusal,
    DeviceRefusedError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    InvalidResolutionError,
    OversizedValueError,
    PersonModelOffError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    UnknownConnectionError,
    UnusableIdentityError,
)
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    CHAT_DEVICES_MAX,
    DEFAULT_NOTIFICATION_REACH,
    DEFAULT_PAGE_SIZE,
    OWNER_PERSON_ID,
    SECRET_VALUE_MAX_BYTES,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ActivationEnding,
    ActivationStop,
    ApprovalEnd,
    ApprovalGiver,
    Belief,
    BeliefBand,
    ChannelIdentity,
    ChatDevice,
    ChatStreamEnd,
    ClassReach,
    ConversationDeletedChange,
    ConversationStartedChange,
    CostBasis,
    CoverageUnrecordedBinding,
    DeletedMessage,
    DeviceAccess,
    DevicesChangedChange,
    DiscloserProvenance,
    EgressBinding,
    GrantScope,
    HolderKind,
    MemoryKind,
    MemoryMark,
    MemoryStanding,
    MemoryStatus,
    MessageAddedChange,
    MessageAuthor,
    MessageDeletedChange,
    NotificationCondition,
    NotificationDispositionKind,
    NotificationPreferences,
    NotificationReach,
    OriginUnrecordedBinding,
    PermissionDecision,
    PermissionOutcome,
    ProcessingStatus,
    ProfileField,
    ProvisioningState,
    QuietWindow,
    ReadingCertainty,
    ReadOutcome,
    RecordedInvocation,
    SecretScope,
    SendOutcome,
    SourceGrant,
    SourceReadRecord,
    SpendPeriod,
    SpendTotal,
    StoryMember,
    StoryMemberKind,
    SupportDirection,
    SupportHolder,
    SupportOrigin,
    ToolOutcome,
    TranscriptMessage,
    UserMessage,
    check_story_page,
    encodable_text,
    secret_value,
    story_move_members,
    story_note_ids,
    story_note_text,
)
from ai_assistant.interfaces import episode_inspection, person_inspection, story_inspection
from ai_assistant.interfaces.devices import this_device as _this_device
from ai_assistant.interfaces.gateway import Disclosure, Note, run_gateway
from ai_assistant.interfaces.gateway import exits as gateway_exits
from ai_assistant.secret_store import KeyringSecretStore
from ai_assistant.wire import (
    GRANTABLE_SCOPES,
    ConnectionClosedError,
    HubClient,
    HubEngineClient,
    HubUnavailableError,
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
from ai_assistant.wire.codec import usable_identity
from ai_assistant.wire.envelope import CHANGE_STREAM_HEARTBEAT

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import (
        Approval,
        BeliefSummary,
        CanonicalDestination,
        ChatChange,
        ConnectedAccount,
        ConnectionAct,
        ConversationDigest,
        ConversationState,
        ConversationSummary,
        DestinationProtocol,
        DeviceChange,
        EgressSpan,
        GrantableSource,
        HeldNotification,
        NotificationCandidate,
        PersonModelEdit,
        QuestionPart,
        StoryHeader,
        StoryOutcome,
        ToolCost,
        ToolInvocation,
        TranscriptPage,
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

#: The ``beliefs`` command's enum-typed filters, hoisted to module scope, the
#: module-level-singleton form ruff's B008 requires of an enum-annotated option.
#: Each may be repeated; the values within one flag are a union and the two flags
#: compose by conjunction, which is the façade's own rule relayed unchanged
#: (ADR-0073 §1).
_BELIEFS_BAND_OPTION = typer.Option(
    None,
    "--band",
    help="Only show beliefs in this band (repeatable). Default: every band.",
)


_BELIEFS_KIND_OPTION = typer.Option(
    None,
    "--kind",
    help=(
        "Only show records of this kind (repeatable). Default: memories alone — pass "
        "--kind episodic to see captured conversation turns."
    ),
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
    fold away silently — ``(NOTIFY, NOTIFY)`` is a caller that has lost track of what
    it is asking for — and both the client and the engine raise ``ValueError`` for
    it. That is not an :class:`AssistantError` either, so without this
    ``assistant grant calendar --scope notify --scope notify`` escapes as a traceback
    exactly as a blank source does.

    **Empty needs no check here**: the option is required, so Typer refuses a call
    that names no scope at all before this runs.

    **A use a new grant may no longer name never reaches this**: :func:`_offered_scope`
    refuses it during the parse, with the reason (ADR-0294 §4).

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


#: What the ``--scope`` option shows as its choices: the uses a new grant may name
#: (ADR-0294 §4), rather than every member the enum still carries. Typer would
#: otherwise list the type's members, ``ingest`` among them, beside a help string
#: that no longer offers it.
_SCOPE_METAVAR: Final = "<" + "|".join(use.value for use in GRANTABLE_SCOPES) + ">"


def _offered_scope(value: str) -> GrantScope:
    """Parse one ``--scope`` value against the uses a new grant may name (ADR-0294 §4).

    **The parse is this function's rather than Typer's enum conversion**, because
    the latter's refusal of an unknown value enumerates the type's members — so a
    typo would be answered with a list offering ``ingest``, which is the offer
    ADR-0294 §4 withdraws, and following that suggestion would meet a second
    refusal. Here an unknown value is answered with :data:`GRANTABLE_SCOPES` alone,
    and ``ingest`` with a sentence saying why it can no longer be granted.

    Args:
        value: One ``--scope`` value as typed.

    Returns:
        The use it names.

    Raises:
        BadParameter: If it names no use a new grant may name.
    """
    offered = ", ".join(f"'{use.value}'" for use in GRANTABLE_SCOPES)
    if value in {use.value for use in GRANTABLE_SCOPES}:
        return GrantScope(value)
    if value in {use.value for use in GrantScope}:
        msg = (
            f"'{value}' can no longer be granted: nothing reads a source for that use "
            f"any more. Choose from {offered}"
        )
        raise typer.BadParameter(msg)
    msg = f"'{value}' is not one of {offered}"
    raise typer.BadParameter(msg)


#: ``assistant grant``'s repeatable scope flag, hoisted to module scope for the
#: reason the ``beliefs`` enum options are (ruff's B008). Required
#: with no default, deliberately: ADR-0097 §2 refuses an empty scope at
#: construction, and a *default* scope would be this adapter deciding what a user
#: permitted — the one decision ADR-0097 §8 says nothing may make for them.
#:
#: **The help names every use a new grant may name, and no other** (ADR-0294 §4,
#: narrowing ADR-0133 §6's every-member rule for this one offer). It is the hub's
#: vocabulary for a *new* grant that the surface may not disagree with: offering a
#: use the hub refuses would be the disagreement ADR-0097 §8 names, arriving from
#: the other side. :func:`_offered_scope` is the parse, so a typo is answered with
#: the same two uses and ``ingest`` with a sentence saying why it is refused.
_GRANT_SCOPE_OPTION = typer.Option(
    ...,
    "--scope",
    parser=_offered_scope,
    callback=_distinct_scope,
    metavar=_SCOPE_METAVAR,
    help=(
        "What this grant allows: 'notify' to read the source in order to raise "
        "things with you unprompted."
    ),
)

#: The same option on ``amend``, and it carries the same uses for the same reason:
#: an amendment's new scope is a new grant, so ADR-0318 §6:2 offers it ``NOTIFY``
#: alone, and not ``INGEST``, and ADR-0139 §4:6 takes the new scope from that
#: offer. Nothing here may be trimmed further on the ground that the user granted a
#: narrower set last time — that would be the surface deciding what the user
#: permits on their behalf (ADR-0139 §3's second clause).
_AMEND_SCOPE_OPTION = typer.Option(
    ...,
    "--scope",
    parser=_offered_scope,
    callback=_distinct_scope,
    metavar=_SCOPE_METAVAR,
    help=(
        "What the *new* grant allows, replacing the old one entirely: 'notify' to "
        "read the source in order to raise things with you unprompted."
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
    """The wall-clock 'now' the notification listing is rendered against.

    The same module-level clock convention every subsystem uses
    (``datetime.now(UTC)``). Named so a test can substitute it for a deterministic
    timestamp.
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
    _print(f"ai-assistant [bold cyan]{__version__}[/]")


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
    """:func:`_present_id` for the id parameters that may be absent.

    ``chat --conversation`` and every parameter like it default to ``None``, which is
    the "none named" state — the one thing this must not turn into a blank, and the
    reason it cannot simply be :func:`_present_id`. The shape
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
    normal usage error (exit code 2) before any engine is built.
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
#: ``beliefs`` and ``grant`` enum options are (ruff's B008). Optional
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

    Each row shows the id ``assistant chat --conversation`` takes, when the
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
        ..., callback=_present_id, help="The id of the conversation whose episodes to forget."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The conversation is still shown first."
    ),
) -> None:
    """Forget one conversation's episodes, after showing you what.

    You are shown how many turns it holds and when it ran — the count and span
    rather than every turn, which is what a person can actually judge at a prompt —
    and they are forgotten only once you agree. ``--yes`` skips the question, not the
    rendering.

    Forgetting removes the conversation's episodes from the assistant's memory, so it
    no longer recalls them anywhere else. The conversation and its transcript stay:
    the assistant still reads it while you keep talking there, and only deleting
    removes it (ADR-0293 §5:7).
    """
    code = asyncio.run(_forget_conversation(conversation_id, assume_yes=yes))
    raise typer.Exit(code)


_EPISODES_STATUS_OPTION = typer.Option(None, "--status")


@app.command()
def episodes(
    limit: int = typer.Option(50, "--limit", min=1, max=100),
    cursor: str | None = typer.Option(None, "--cursor"),
    channel_type: str | None = typer.Option(None, "--channel-type"),
    channel_instance: str | None = typer.Option(None, "--channel-instance"),
    status: ProcessingStatus | None = _EPISODES_STATUS_OPTION,
) -> None:
    """List live episodes, newest first; repeat filters when following a cursor."""
    if (channel_type is None) != (channel_instance is None):
        raise typer.BadParameter("--channel-type and --channel-instance must be supplied together")
    try:
        channel = (
            None
            if channel_type is None or channel_instance is None
            else ChannelIdentity(channel_type=channel_type, instance_id=channel_instance)
        )
        selected, selected_status, _ = check_episode_list(channel, status, cursor, limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    raise typer.Exit(
        asyncio.run(
            _list_episodes(channel=selected, status=selected_status, cursor=cursor, limit=limit)
        )
    )


@app.command()
def episode(
    episode_id: str = typer.Argument(..., help="Exact stored ID; quote whitespace or an empty ID."),
    as_json: bool = typer.Option(
        False, "--json", help="Print the complete verified canonical JSON."
    ),
) -> None:
    """Inspect one live episode; never display an incomplete chunk assembly.

    Retention expiry, where a retention window is set, removes an episode from live
    memory; explicit forgetting deletes it.
    """
    try:
        check_episode_detail(episode_id, None, 0, 65536)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    raise typer.Exit(asyncio.run(_show_episode(episode_id, as_json=as_json)))


async def _list_episodes(
    *,
    channel: ChannelIdentity | None,
    status: ProcessingStatus | None,
    cursor: str | None,
    limit: int,
) -> int:
    try:
        engine = await _open_engine()
        page = await engine.episodes(channel=channel, status=status, cursor=cursor, limit=limit)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    episode_inspection.render_page(console, page)
    return _EXIT_OK


async def _show_episode(episode_id: str, *, as_json: bool) -> int:
    """Read one episode whole and render it.

    The human detail also names the stories the episode's activation belongs to
    directly (ADR-0289 §5:3), read after the record is verified. ``--json`` prints
    the canonical record and nothing else, so it asks for no stories.
    """
    stories: tuple[StoryHeader, ...] | None = None
    try:
        engine = await _open_engine()
        detail = await episode_inspection.read_detail(engine, episode_id)
        if detail is not None and not as_json:
            processing = detail[1].processing_record
            if processing is not None:
                stories = await engine.activation_stories(processing.activation_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if detail is None:
        console.print("Episode unavailable, expired, or deleted; incomplete content discarded.")
        return _EXIT_ERROR
    encoded, record = detail
    if as_json:
        console.print(encoded, markup=False, emoji=False, highlight=False, soft_wrap=True)
    else:
        episode_inspection.render_detail(console, record, stories=stories)
    return _EXIT_OK


# --- stories (ADR-0289 §5) -------------------------------------------------------

#: The owner's story commands. **For testing**: this group is how the store's rules
#: and a story's summary are exercised by hand, and its help says so (ADR-0289 §5:1),
#: ADR-0300 §8:4 adding the story commands under that clause. Rendering and argument
#: parsing only: what a write may do, what of a summary the owner is shown and where a
#: matter stands are the story store's and the engine's to decide.
story_app = typer.Typer(
    name="story",
    help=(
        "For testing: create, link, unlink, merge, split, list and show stories by "
        "hand; read a story's summary and where its matter stands; add a note to it; "
        "and move activations between stories. A story holds which experiences belong "
        "to the same matter. Name a member with --activation (an activation id) or "
        "--story (a story id)."
    ),
    no_args_is_help=True,
)
app.add_typer(story_app, name="story")


def _present_ids(values: list[str] | None) -> list[str]:
    """:func:`_present_id` over each value of a repeatable id option."""
    return [_present_id(value) for value in values or []]


_STORY_ACTIVATION_OPTION = typer.Option(
    None,
    "--activation",
    "-a",
    callback=_present_ids,
    help="An activation member, by its activation id. Repeat for more.",
)
_STORY_STORY_OPTION = typer.Option(
    None,
    "--story",
    "-s",
    callback=_present_ids,
    help="A story member, by its story id. Repeat for more.",
)
_STORY_NOTE_OPTION = typer.Option(
    None,
    "--note",
    "-n",
    help=(
        "A note that goes, by the number 'assistant story summary' shows after its #. "
        "Repeat for more. A note the story does not hold is passed over; no note goes "
        "unless it is named."
    ),
)
_STORY_ID_ARGUMENT = typer.Argument(
    ..., callback=_present_id, help="The story's id (see 'assistant story list')."
)


def _story_members(activations: list[str] | None, stories: list[str] | None) -> list[StoryMember]:
    """The members a write names, each carrying the kind its option stated (ADR-0289 §2).

    The kind is never read off the id: ``--activation`` and ``--story`` say which.
    Activations come first, then stories, each in the order given, and that is the
    order the write names them in.
    """
    return [
        *(StoryMember(kind=StoryMemberKind.ACTIVATION, id=value) for value in activations or []),
        *(StoryMember(kind=StoryMemberKind.STORY, id=value) for value in stories or []),
    ]


async def _write_story(
    applied: str, write: Callable[[AssistantEngine], Awaitable[StoryOutcome]]
) -> int:
    """Run one story write and render its outcome; a refusal exits non-zero."""
    try:
        engine = await _open_engine()
        outcome = await write(engine)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    return _EXIT_OK if story_inspection.render_outcome(console, applied, outcome) else _EXIT_ERROR


@story_app.command("create")
def story_create(
    activation: list[str] | None = _STORY_ACTIVATION_OPTION,
    story: list[str] | None = _STORY_STORY_OPTION,
) -> None:
    """Create a story holding the members named."""
    members = _story_members(activation, story)
    raise typer.Exit(
        asyncio.run(_write_story("Created story", lambda engine: engine.create_story(members)))
    )


@story_app.command("link")
def story_link(
    story_id: str = _STORY_ID_ARGUMENT,
    activation: list[str] | None = _STORY_ACTIVATION_OPTION,
    story: list[str] | None = _STORY_STORY_OPTION,
) -> None:
    """Add the members named to a story; one already in it is passed over."""
    members = _story_members(activation, story)
    raise typer.Exit(
        asyncio.run(
            _write_story("Linked to story", lambda engine: engine.link_story(story_id, members))
        )
    )


@story_app.command("unlink")
def story_unlink(
    story_id: str = _STORY_ID_ARGUMENT,
    activation: list[str] | None = _STORY_ACTIVATION_OPTION,
    story: list[str] | None = _STORY_STORY_OPTION,
) -> None:
    """Remove the members named from a story; one not in it is passed over."""
    members = _story_members(activation, story)
    raise typer.Exit(
        asyncio.run(
            _write_story(
                "Unlinked from story", lambda engine: engine.unlink_story(story_id, members)
            )
        )
    )


@story_app.command("merge")
def story_merge(
    story_id: str = typer.Argument(
        ..., callback=_present_id, help="The story to merge; it is left empty, marked merged."
    ),
    into: str = typer.Option(
        ..., "--into", callback=_present_id, help="The story it is merged into."
    ),
) -> None:
    """Merge one story into another, which takes its members."""
    raise typer.Exit(
        asyncio.run(
            _write_story("Merged into story", lambda engine: engine.merge_stories(story_id, into))
        )
    )


@story_app.command("split")
def story_split(
    story_id: str = _STORY_ID_ARGUMENT,
    activation: list[str] | None = _STORY_ACTIVATION_OPTION,
    story: list[str] | None = _STORY_STORY_OPTION,
    note: list[int] | None = _STORY_NOTE_OPTION,
) -> None:
    """Move the members named out of a story into a new story, with the notes named."""
    members = _story_members(activation, story)
    notes = _story_notes(note)
    raise typer.Exit(
        asyncio.run(
            _write_story(
                "Split the members named into new story",
                lambda engine: engine.split_story(story_id, members, notes=notes),
            )
        )
    )


def _story_notes(notes: list[int] | None) -> tuple[int, ...]:
    """The notes a split or a move names (ADR-0303 §10:4), refused here if malformed."""
    try:
        return story_note_ids(notes or [])
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="'--note'") from exc


@story_app.command("list")
def story_list(
    limit: int = typer.Option(DEFAULT_PAGE_SIZE, "--limit", help="How many stories at most."),
    cursor: int | None = typer.Option(None, "--cursor", help="A previous page's next cursor."),
) -> None:
    """List every story, newest first, each with its summary's first line where it has one.

    A summary resting on outside content is labelled so. You are shown every summary,
    whatever it was written from.
    """
    try:
        check_story_page(cursor, limit)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    raise typer.Exit(asyncio.run(_list_stories(cursor=cursor, limit=limit)))


async def _list_stories(*, cursor: int | None, limit: int) -> int:
    try:
        engine = await _open_engine()
        listing = await story_inspection.read_listing(engine, cursor=cursor, limit=limit)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    story_inspection.render_listing(console, listing)
    return _EXIT_OK


@story_app.command("show")
def story_show(story_id: str = _STORY_ID_ARGUMENT) -> None:
    """Show a story: its members, then its change log, oldest first.

    An activation member is its episode's summary, in progress while the episode is
    open, or forgotten once it is gone; a story member is its id and member count. A
    merged story shows only the story it was merged into.
    """
    raise typer.Exit(asyncio.run(_show_story(story_id)))


async def _show_story(story_id: str) -> int:
    return await _read_story(
        story_id,
        lambda engine: story_inspection.read_story(engine, story_id),
        story_inspection.render_story,
    )


async def _read_story[T](
    story_id: str,
    read: Callable[[AssistantEngine], Awaitable[T | None]],
    render: Callable[[Console, T], None],
) -> int:
    """Run one story read and render it; no such story exits non-zero."""
    try:
        engine = await _open_engine()
        result = await read(engine)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if result is None:
        console.print(
            f"No story {story_inspection.quoted(story_id)}.",
            markup=False,
            emoji=False,
            highlight=False,
            soft_wrap=True,
        )
        return _EXIT_ERROR
    render(console, result)
    return _EXIT_OK


# --- the story commands (ADR-0300 §8) ---------------------------------------------


@story_app.command("summary")
def story_summary(story_id: str = _STORY_ID_ARGUMENT) -> None:
    """Show a story's summary: when it was last tidied, its lines, then its notes.

    The summary and a note resting on outside content are labelled so. You are shown the
    summary whatever it was written from, a forgotten conversation included. Each note
    shows its number, by which a split or a move names it, and whether it is pending.
    A merged story shows only the story it was merged into.
    """
    raise typer.Exit(
        asyncio.run(
            _read_story(
                story_id,
                lambda engine: engine.story_summary(story_id),
                story_inspection.render_summary,
            )
        )
    )


@story_app.command("standing")
def story_standing(story_id: str = _STORY_ID_ARGUMENT) -> None:
    """Show where a story's matter stands, worked out from the records.

    What was done, the timeline of its episodes, most recent first, and the related
    matters: the stories it is part of and the stories it contains.
    """
    raise typer.Exit(
        asyncio.run(
            _read_story(
                story_id,
                lambda engine: engine.story_standing(story_id),
                story_inspection.render_standing,
            )
        )
    )


@story_app.command("note")
def story_note(
    story_id: str = _STORY_ID_ARGUMENT,
    text: str = typer.Argument(..., help="The note, as you would write it."),
) -> None:
    """Add a note of your own to a story; it is pending until the summary is tidied."""
    try:
        written = story_note_text(text)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="TEXT") from exc
    raise typer.Exit(asyncio.run(_note_story(story_id, written)))


async def _note_story(story_id: str, text: str) -> int:
    try:
        engine = await _open_engine()
        outcome = await engine.add_story_note(story_id, text)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    written = story_inspection.render_note_outcome(console, story_id, outcome)
    return _EXIT_OK if written else _EXIT_ERROR


@story_app.command("move")
def story_move(
    story_id: str = typer.Argument(
        ..., callback=_present_id, help="The story the activations or notes are moved out of."
    ),
    to: str = typer.Option(
        ..., "--to", callback=_present_id, help="The story they are moved into."
    ),
    activation: list[str] | None = _STORY_ACTIVATION_OPTION,
    note: list[int] | None = _STORY_NOTE_OPTION,
) -> None:
    """Move the activations and notes named from one story to another.

    Name notes and no activation to move only the notes (ADR-0304 §9); the move is
    refused where the story holds none of them.
    """
    try:
        members = story_move_members(story_id, to, _story_members(activation, None))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    notes = _story_notes(note)
    raise typer.Exit(
        asyncio.run(
            _write_story(
                "Moved to story",
                lambda engine: engine.move_story_members(story_id, to, members, notes=notes),
            )
        )
    )


# --- the chat space (ADR-0293 §2-§5, §8, §11; ADR-0296 §6) -------------------
#
# The conversation as a hosted medium: start one, write in it and follow it, read
# its transcript, delete a message or the conversation, and keep "my devices" and a
# conversation's devices. Each act is one engine call relayed. What this adds, and
# nothing more, is which device this command line is, the message id it chooses for
# each message (ADR-0293 §4:1), and the cursor a followed conversation's change
# stream is opened from and reopened from (ADR-0296 §4:4, §6:1-§6:2). Forgetting is
# ``forget-conversation``, offered beside deleting and never folded into it (§2:7).

#: How long a chat waits before opening its change stream again once it is lost, in
#: seconds, the first time. Each further attempt waits twice as long as the one
#: before, up to :data:`_CHAT_RETRY_MAX_SECONDS`, and an opened stream starts over.
_CHAT_RETRY_SECONDS: Final = 1.0

#: The longest a chat waits between attempts to open its change stream again, in
#: seconds: the hub's heartbeat interval, so a hub that comes back is followed again
#: within about the time a live one would have taken to say it was alive.
_CHAT_RETRY_MAX_SECONDS: Final = CHANGE_STREAM_HEARTBEAT.total_seconds()

#: How many of a conversation's recent messages a snapshot shows (ADR-0293 §5:13).
_CHAT_SNAPSHOT_LIMIT: Final = 50

#: What each access is called on screen (ADR-0293 §3:5).
_ACCESS_PHRASES: Final = {
    DeviceAccess.READ_WRITE: "reads and writes",
    DeviceAccess.READ: "reads only",
    DeviceAccess.WRITE: "writes only",
}

#: How the last activation started from a conversation ended, as one sentence
#: (ADR-0293 §8:3, ADR-0295 §3:4). After a restart a device offers to send again
#: rather than wait for a reply that never comes (§8).
_ENDING_PHRASES: Final = {
    ActivationEnding.DONE: "The assistant is done.",
    ActivationEnding.COULDNT_FINISH: "The assistant couldn't finish.",
    ActivationEnding.INTERRUPTED: "The assistant was interrupted; send your message again?",
    ActivationEnding.STOPPED: "The assistant was stopped.",
}

#: What a stop found, as fixed text (ADR-0297 §5:8, ADR-0295 §2). **Only what the
#: answer means is said**: ``STOPPED`` promises what ADR-0295 §2 guarantees from the
#: moment the stop landed and nothing more — a stage already running finishes under
#: its own deadlines (ADR-0297 §4), so "stopped" is never said to mean "halted now",
#: and nothing already sent is said to be called back. The two non-acting answers
#: say that nothing was written, which is §5:5's and §5:6's whole content; the
#: second claims no more than that the hub holds nothing saying the activation ran.
_STOP_PHRASES: Final = {
    ActivationStop.STOPPED: (
        "[bold]Stopped.[/] Nothing new starts in that work from now on, and it writes "
        "nothing more into its conversation. What it was in the middle of finishes "
        "first, and anything it had already sent is not called back; how that turned "
        "out is recorded."
    ),
    ActivationStop.ALREADY_ENDED: (
        "[yellow]That had already ended,[/] so this stopped nothing and recorded nothing."
    ),
    ActivationStop.NO_SUCH_ACTIVATION: (
        "[yellow]Nothing here says work of that id ran,[/] so nothing was stopped. While "
        "the assistant works, 'assistant chat' and 'assistant conversation' show the id "
        "to give."
    ),
}

#: The exit code of each answer to a stop. **A table rather than a membership test**, so
#: a member added to the vocabulary is a ``KeyError`` here rather than a silent arrival
#: on whichever side an expression negated. Only ``STOPPED`` acted; the other two wrote
#: nothing (ADR-0297 §5:5, §5:6), so a script reading success off either would be
#: reading a stop that did not happen.
_STOP_EXIT_CODES: Final = {
    ActivationStop.STOPPED: _EXIT_OK,
    ActivationStop.ALREADY_ENDED: _EXIT_ERROR,
    ActivationStop.NO_SUCH_ACTIVATION: _EXIT_ERROR,
}

#: What the chat prompt understands besides a message.
_CHAT_HELP: Final = (
    "[dim]Type a message and press Enter to send it. '/reply N <text>' replies to "
    "message #N — that is also how you correct the assistant. '/quit' (or end of "
    "input) leaves; '//' sends a message that starts with '/'.[/]"
)

_CHAT_DEVICE_OPTION = typer.Option(
    None,
    "--device",
    callback=_present_optional_id,
    metavar="DEVICE_ID",
    help=(
        "The device this command line writes as, for a hub on another machine: this "
        "machine's overlay identity, read from the overlay agent when omitted. On the "
        "hub's own machine the device is 'hub'."
    ),
)
_DEVICE_ADD_OPTION = typer.Option(
    None,
    "--add",
    callback=_present_ids,
    metavar="DEVICE_ID",
    help="Add this device. Repeat for more. Adding one says its screen is private.",
)
_DEVICE_REMOVE_OPTION = typer.Option(
    None, "--remove", callback=_present_ids, metavar="DEVICE_ID", help="Remove this device."
)
_DEVICE_ACCESS_OPTION = typer.Option(
    DeviceAccess.READ_WRITE,
    "--access",
    help="What the devices --add names may do: read, write, or both (read_write).",
)


def _position_argument(value: int) -> int:
    """Refuse a message number the engine would refuse, while Typer is still parsing.

    The engine's refusal is a ``ValueError`` (ADR-0085 §9), which would escape a
    command's error boundary as a traceback; refused here it is a usage error, exit 2,
    before any client is built — :func:`_page_argument`'s reason.

    Raises:
        BadParameter: If the value is not in ``[1, 2**63)``.
    """
    if not 1 <= value < _PAGE_BOUND:
        msg = f"must be between 1 and {_PAGE_BOUND - 1}"
        raise typer.BadParameter(msg)
    return value


def _optional_position_argument(value: int | None) -> int | None:
    """:func:`_position_argument` for ``--before``, which may be absent."""
    return None if value is None else _position_argument(value)


@app.command()
def chat(
    conversation: str | None = typer.Option(
        None,
        "--conversation",
        "-c",
        callback=_present_optional_id,
        help="Open this conversation (see 'assistant conversations'). Omit it to start one.",
    ),
    device: str | None = _CHAT_DEVICE_OPTION,
) -> None:
    """Talk in a conversation: its recent messages, then each one as it arrives.

    Each line you type is written into the conversation as a message, and is
    received once the conversation has recorded it. The assistant's messages, and
    any written from your other devices, are shown as they arrive, and so is what the
    assistant is doing: working, or how it last ended. Writing while it works is
    fine: each message starts its own work, and one that carries on what is running
    may be taken up with it.

    This device has to be one of the conversation's devices to write in it. Where it
    is not, you are asked whether to add it, which is saying its screen is private.
    """
    try:
        code = asyncio.run(_chat(conversation, device=device))
    except KeyboardInterrupt:
        _print("\n[dim]Left the conversation. It is still there.[/]")
        code = _EXIT_OK
    raise typer.Exit(code)


@app.command("start-conversation")
def start_conversation() -> None:
    """Start an empty conversation, shown on your devices.

    Prints its id, which 'assistant chat --conversation' opens. A conversation is
    started only this way or by 'assistant chat': writing a message never starts one.
    """
    raise typer.Exit(asyncio.run(_with_engine(_drive_start_conversation)))


@app.command()
def conversation(
    conversation_id: str = typer.Argument(
        ..., callback=_present_id, help="The conversation's id (see 'assistant conversations')."
    ),
    before: int | None = typer.Option(
        None,
        "--before",
        callback=_optional_position_argument,
        metavar="N",
        help="Show the messages before message #N, to read further back.",
    ),
    limit: int = typer.Option(
        _CHAT_SNAPSHOT_LIMIT,
        "--limit",
        callback=_page_argument,
        help="How many messages to show at most.",
    ),
) -> None:
    """Show one conversation: its devices, what the assistant is doing, its messages.

    The most recent messages are shown; ``--before`` reads further back. A deleted
    message is shown as deleted, so a reply to it still makes sense.
    """
    raise typer.Exit(
        asyncio.run(
            _with_engine(
                lambda engine: _drive_show_conversation(
                    engine, conversation_id, before=before, limit=limit
                )
            )
        )
    )


@app.command("delete-message")
def delete_message(
    conversation_id: str = typer.Argument(..., callback=_present_id, help="The conversation."),
    position: int = typer.Argument(
        ..., callback=_position_argument, help="The message's number, as #N shows it."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The message is still shown first."
    ),
) -> None:
    """Delete one message, of yours or the assistant's, after showing it.

    It is removed from the conversation on every device, and a reply to it stays,
    naming a deleted message. The assistant's memory is not changed by deleting.
    """
    confirm: Callable[[], bool] = (lambda: True) if yes else _confirm_delete_message
    raise typer.Exit(
        asyncio.run(
            _with_engine(
                lambda engine: _drive_delete_message(
                    engine, conversation_id, position, confirm=confirm
                )
            )
        )
    )


@app.command("delete-conversation")
def delete_conversation(
    conversation_id: str = typer.Argument(
        ..., callback=_present_id, help="The id of the conversation to delete."
    ),
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The conversation is still shown first."
    ),
) -> None:
    """Delete a conversation and its messages, after showing you which.

    Deleting forgets nothing: what the assistant remembers of the conversation stays
    until you forget it with 'assistant forget-conversation', before or after deleting.
    """
    confirm: Callable[[], bool] = (lambda: True) if yes else _confirm_delete_conversation
    raise typer.Exit(
        asyncio.run(
            _with_engine(
                lambda engine: _drive_delete_conversation(engine, conversation_id, confirm=confirm)
            )
        )
    )


@app.command()
def stop(
    activation_id: str = typer.Argument(
        ...,
        callback=_present_id,
        help="The id 'assistant chat' or 'assistant conversation' shows while it works.",
    ),
) -> None:
    """Stop what the assistant is working on, naming it by its id.

    Nothing new starts in that work once the stop lands, and it writes nothing more
    into its conversation. **It is not cut off mid-step**: what it was in the middle
    of finishes first, and anything it had already sent is not called back — how that
    turned out is recorded. The conversation then shows it as stopped.

    Writing "stop" in a conversation is a message, read like any other: the assistant
    may stop the work for it.

    Where the work had already ended, or nothing here says it ran, this says so and
    changes nothing.
    """
    raise typer.Exit(asyncio.run(_with_engine(lambda engine: _drive_stop(engine, activation_id))))


@app.command("my-devices")
def my_devices(
    add: list[str] | None = _DEVICE_ADD_OPTION,
    remove: list[str] | None = _DEVICE_REMOVE_OPTION,
    access: DeviceAccess = _DEVICE_ACCESS_OPTION,
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. What adding says is still shown."
    ),
) -> None:
    """Show your devices, or change them: every new conversation is shown on them.

    Adding a device says its screen is private. A conversation already started keeps
    its own devices; 'assistant conversation-devices' changes one.
    """
    change = _device_change(add, remove, access)
    confirm: Callable[[], bool] = (lambda: True) if yes else _confirm_device_statement
    raise typer.Exit(
        asyncio.run(
            _with_engine(lambda engine: _drive_devices(engine, None, change, confirm=confirm))
        )
    )


@app.command("conversation-devices")
def conversation_devices(
    conversation_id: str = typer.Argument(..., callback=_present_id, help="The conversation."),
    add: list[str] | None = _DEVICE_ADD_OPTION,
    remove: list[str] | None = _DEVICE_REMOVE_OPTION,
    access: DeviceAccess = _DEVICE_ACCESS_OPTION,
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. What adding says is still shown."
    ),
) -> None:
    """Show one conversation's devices, or change them, leaving your devices alone.

    Adding a device to a conversation says its screen is private, for that
    conversation; removing one keeps the conversation off it, as on a shared tablet.
    """
    change = _device_change(add, remove, access)
    confirm: Callable[[], bool] = (lambda: True) if yes else _confirm_device_statement
    raise typer.Exit(
        asyncio.run(
            _with_engine(
                lambda engine: _drive_devices(engine, conversation_id, change, confirm=confirm)
            )
        )
    )


class _DeviceChange(NamedTuple):
    """The devices a command was asked to add and remove, checked before any I/O."""

    add: tuple[ChatDevice, ...]
    remove: tuple[str, ...]

    @property
    def empty(self) -> bool:
        """Whether nothing was asked, so the command only shows the set."""
        return not self.add and not self.remove


def _device_change(
    add: list[str] | None, remove: list[str] | None, access: DeviceAccess
) -> _DeviceChange:
    """Build the change ``--add``/``--remove`` ask for, or refuse it as a usage error.

    A device named on both sides, or twice on one, is refused rather than resolved
    by an order nobody chose; an id ``ChatDevice`` refuses is refused here, before any
    client is built, rather than as a ``ValueError`` out of the call.

    Raises:
        BadParameter: If a device is named twice, or an id is not one a device has.
    """
    added = list(add or [])
    removed = list(remove or [])
    named = added + removed
    if len(set(named)) != len(named):
        msg = "name each device once, to add it or to remove it"
        raise typer.BadParameter(msg)
    try:
        devices = tuple(ChatDevice(device_id=one, access=access) for one in added)
    except ValueError as exc:
        msg = "a device id must be a non-blank id"
        raise typer.BadParameter(msg) from exc
    return _DeviceChange(add=devices, remove=tuple(removed))


async def _with_engine(drive: Callable[[AssistantEngine], Awaitable[int]]) -> int:
    """Obtain a client of the hub and run one command against it (ADR-0042 §7).

    The one error boundary :func:`_list_conversations` and its siblings each spell
    out, shared by the chat space's commands: a failure to reach the hub is
    rendered and mapped to a non-zero exit code rather than escaping as a traceback.
    """
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    try:
        return await drive(engine)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR


async def _chat(conversation_id: str | None, *, device: str | None) -> int:
    """Load settings, name this device, obtain the hub, and hold the conversation open.

    One error boundary over every stage (ADR-0042 §7). Lines are read from the
    terminal on a thread of their own (:class:`_TerminalLines`), so the conversation
    keeps being followed while you type.

    **This device is named once per command.** Where the hub is on another machine
    and ``--device`` names nothing, it is read from this machine's overlay agent — the
    agent ``client_overlay_agent_socket`` locates, which is the one the connection
    to the hub asks as well (:func:`_open_engine`).
    """
    try:
        settings = load_settings()
        agent = (
            None
            if settings.remote_hub_address is None
            else local_agent(settings.client_overlay_agent_socket)
        )
        this_device = await _this_device(settings, named=device, agent=agent)
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    lines = _TerminalLines(asyncio.get_running_loop())
    return await _drive_chat(
        engine,
        conversation_id,
        device_id=this_device,
        read_line=lines.next_line,
        confirm=_confirm_device_statement,
        start_reading=lines.start,
    )


class _TerminalLines:
    """Lines typed at the terminal, read on a daemon thread and handed to the loop.

    A daemon thread, and not ``asyncio.to_thread``: a read blocked on the terminal
    cannot be cancelled, and the default executor is waited for when the loop shuts
    down, so leaving with Ctrl-C would hang until the next Enter. A daemon thread is
    abandoned at exit instead.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the lines to the loop they are handed to; nothing is read yet."""
        self._loop = loop
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()

    def start(self) -> None:
        """Begin reading, once every prompt before the conversation has been answered."""
        threading.Thread(target=self._read, name="assistant-chat-input", daemon=True).start()

    async def next_line(self) -> str | None:
        """The next line typed, without its line ending, or ``None`` at end of input."""
        return await self._queue.get()

    def _read(self) -> None:
        while True:
            try:
                line = sys.stdin.readline()
            except OSError, ValueError:
                line = ""
            handed = line.rstrip("\r\n") if line else None
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, handed)
            except RuntimeError:  # the loop has closed: nobody is reading any more
                return
            if handed is None:
                return


@final
class _ChatView:
    """What a followed conversation has shown, and where it follows from.

    Holds the cursor (the one state ADR-0296 §6:2 lets the command line keep), the
    entries it has shown so a reply's reference can say its message was deleted
    (ADR-0293 §5:8), the ids of messages this device is sending so their arrival is
    not shown twice, and the current state last shown (§8).
    """

    def __init__(self, conversation_id: str, *, device_id: str, cursor: int) -> None:
        """Start following ``conversation_id`` from ``cursor``."""
        self.conversation_id = conversation_id
        self.device_id = device_id
        self.cursor = cursor
        self.entries: dict[int, TranscriptMessage | DeletedMessage] = {}
        self.sending: set[str] = set()
        self.state: ConversationState | None = None

    def show_page(self, page: TranscriptPage) -> None:
        """Show a snapshot of the conversation's messages, and follow from its ``as_of``."""
        self.cursor = page.as_of
        if not page.entries:
            _print("[dim]No messages yet.[/]")
        elif page.entries[0].position > 1:
            _print(
                f"[dim]Earlier messages: assistant conversation "
                f"{_safe(self.conversation_id)} --before {page.entries[0].position}[/]"
            )
        for entry in page.entries:
            self.entries[entry.position] = entry
            _render_chat_entry(entry, known=self.entries)

    def show_state(self, state: ConversationState) -> None:
        """Show what the assistant is doing, where it changed since last shown (§8)."""
        previous = self.state
        self.state = state
        if previous is not None and previous == state:
            return
        if state.working:
            if (
                previous is None
                or not previous.working
                or previous.activation_ids != state.activation_ids
            ):
                _print("[dim]The assistant is working… you can keep writing.[/]")
                _print_stop_hint(state)
            return
        if state.last_ended is None:
            return
        if previous is None or previous.working or previous.last_ended != state.last_ended:
            _print(f"[dim]{_ENDING_PHRASES[state.last_ended]}[/]")

    def apply(self, change: ChatChange) -> bool:
        """Show one change; ``False`` where it ends the conversation (§2:3).

        A change to another conversation, a conversation starting, and a change to
        "my devices" are not this conversation's and are passed over.
        """
        if change.conversation_id != self.conversation_id:
            return True
        match change:
            case MessageAddedChange(message=message):
                self._added(message)
            case MessageDeletedChange(marker=marker):
                self.entries[marker.position] = marker
                _print(f"[dim]Message #{marker.position} was deleted.[/]")
            case ConversationDeletedChange():
                _print("[yellow]This conversation was deleted.[/]")
                return False
            case DevicesChangedChange(devices=devices):
                _print("[dim]This conversation's devices changed:[/]")
                _render_device_set(devices)
                return self.still_shown(devices)
            case ConversationStartedChange():
                pass
            case _:  # pragma: no cover — the union is closed
                assert_never(change)
        return True

    def still_shown(self, devices: Sequence[ChatDevice]) -> bool:
        """Whether this device is still shown the conversation, saying so where not (§3:5)."""
        if any(one.device_id == self.device_id and one.access.reads for one in devices):
            return True
        _print("[yellow]This device is no longer shown this conversation.[/]")
        return False

    def fill(self, snapshot: Sequence[TranscriptMessage | DeletedMessage]) -> None:
        """Show what a change's snapshot holds that this chat has not shown (ADR-0298 §7:6).

        The stream sends a snapshot only with the change that makes this device one of
        the conversation's ends for reading, so a chat shown the conversation all along
        is not sent one. Where one is sent, each entry not shown yet is shown, and a
        marker replacing a message shown says so, so nothing is shown twice.
        """
        for entry in snapshot:
            shown = self.entries.get(entry.position)
            self.entries[entry.position] = entry
            if shown is None:
                _render_chat_entry(entry, known=self.entries)
            elif isinstance(entry, DeletedMessage) and isinstance(shown, TranscriptMessage):
                _print(f"[dim]Message #{entry.position} was deleted.[/]")

    def _added(self, message: TranscriptMessage) -> None:
        """Show a message added, unless it is one this device is sending (§4:4)."""
        self.entries[message.position] = message
        if message.device_id == self.device_id and message.message_id in self.sending:
            return
        _render_chat_entry(message, known=self.entries)


async def _drive_chat(  # noqa: PLR0913 — the engine, the conversation, the device, and the three seams a test replaces: the lines, the prompt, and when reading starts
    engine: AssistantEngine,
    conversation_id: str | None,
    *,
    device_id: str,
    read_line: Callable[[], Awaitable[str | None]],
    confirm: Callable[[], bool],
    start_reading: Callable[[], None] = lambda: None,
    retry_seconds: float = _CHAT_RETRY_SECONDS,
) -> int:
    """Open or start a conversation, show it, and relay each line until you leave.

    The conversation is followed on a task of its own, on the change stream from the
    snapshot's cursor (ADR-0296 §6:1, :func:`_follow_chat`), while lines are read;
    either ending ends the chat. ``start_reading`` is called once the device prompts
    before the conversation are answered, so the terminal is read by one reader at a
    time.
    """
    try:
        opened = await _open_chat(engine, conversation_id, device_id=device_id, confirm=confirm)
        if isinstance(opened, int):
            return opened
        view = await _show_chat(engine, opened, device_id=device_id)
        if view is None:
            return _EXIT_ERROR
        start_reading()
        follower = asyncio.create_task(_follow_chat(engine, view, retry_seconds=retry_seconds))
        try:
            return await _relay_lines(engine, view, read_line=read_line, follower=follower)
        finally:
            follower.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await follower
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR


async def _open_chat(
    engine: AssistantEngine,
    conversation_id: str | None,
    *,
    device_id: str,
    confirm: Callable[[], bool],
) -> str | int:
    """The conversation to follow, with this device an end for both, or an exit code.

    A conversation is started only by asking for one (ADR-0293 §2:1, §2:2), on "my
    devices" as they stand — so where this device is not one of them it is offered
    there first, and where an existing conversation does not have it, it is offered
    for that conversation (§3:2, §3:3). Declining leaves everything as it was.

    **Both reading and writing are needed**, because a chat shows the conversation
    and writes in it: a device that may only write is not shown it, and one that may
    only read cannot write (§3:5). Either is offered both, by the same statement.
    """
    if conversation_id is None:
        mine = await engine.my_devices()
        if not _reads_and_writes(mine, device_id) and not await _offer_device(
            engine, None, mine, device_id, confirm=confirm
        ):
            return _EXIT_OK
        started = await engine.start_conversation()
        _print(f"[green]Started a conversation:[/] [bold cyan]{_safe(started.id)}[/]")
        return started.id
    digest = await engine.conversation(conversation_id)
    if digest is None:
        _render_no_such_conversation(conversation_id)
        return _EXIT_ERROR
    if not _reads_and_writes(digest.devices, device_id) and not await _offer_device(
        engine, conversation_id, digest.devices, device_id, confirm=confirm
    ):
        return _EXIT_OK
    return conversation_id


async def _offer_device(
    engine: AssistantEngine,
    conversation_id: str | None,
    devices: Sequence[ChatDevice],
    device_id: str,
    *,
    confirm: Callable[[], bool],
) -> bool:
    """Say what adding this device means, ask, and make it an end for reading and writing.

    Returns:
        Whether the device was added.
    """
    where = "your devices" if conversation_id is None else "this conversation's devices"
    _print(
        f"\nThis device ([bold]{_safe(device_id)}[/]) is not one of {where} for reading "
        "and writing."
    )
    _render_device_statement(conversation_id)
    added = _with_devices(
        devices, (ChatDevice(device_id=device_id, access=DeviceAccess.READ_WRITE),)
    )
    if added is None:
        _render_devices_full()
        return False
    if not confirm():
        _print("[dim]Left alone. No device was added.[/]")
        return False
    if conversation_id is None:
        await engine.set_my_devices(added)
    else:
        await engine.set_conversation_devices(conversation_id, devices=added)
    return True


async def _show_chat(
    engine: AssistantEngine, conversation_id: str, *, device_id: str
) -> _ChatView | None:
    """Show the conversation's snapshot and current state; ``None`` where it is gone."""
    view = _ChatView(conversation_id, device_id=device_id, cursor=0)
    if not await _show_snapshot(engine, view):
        return None
    _print(_CHAT_HELP)
    return view


async def _show_snapshot(engine: AssistantEngine, view: _ChatView) -> bool:
    """Show the conversation from a snapshot, where this device is still shown it.

    The devices are read **after** the snapshot, so a change to them that the
    snapshot's cursor already covers — and the stream will therefore never deliver — is
    still seen before anything is shown (ADR-0293 §3:5). ``False`` where the
    conversation is gone or this device may no longer read it.
    """
    page = await engine.transcript(view.conversation_id, limit=_CHAT_SNAPSHOT_LIMIT)
    digest = None if page is None else await engine.conversation(view.conversation_id)
    if page is None or digest is None:
        _render_no_such_conversation(view.conversation_id)
        return False
    if not view.still_shown(digest.devices):
        return False
    await _resolve_replies(engine, view.conversation_id, page.entries, into=view.entries)
    view.show_page(page)
    view.show_state(digest.state)
    return True


async def _relay_lines(
    engine: AssistantEngine,
    view: _ChatView,
    *,
    read_line: Callable[[], Awaitable[str | None]],
    follower: asyncio.Task[int],
) -> int:
    """Send each line as it is typed, until input ends, ``/quit``, or the follow ends.

    Whichever comes first ends the chat: the next line, or the follower finishing —
    because the conversation was deleted, this device is no longer shown it, or the
    hub could not be read. A send still waiting for its answer does not hold the end
    off: it is abandoned, and said to be of unknown outcome.
    """
    while True:
        reading = asyncio.ensure_future(read_line())
        await asyncio.wait({reading, follower}, return_when=asyncio.FIRST_COMPLETED)
        if not reading.done():
            reading.cancel()
            return follower.result()
        line = reading.result()
        if line is None:
            return _EXIT_OK
        handling = asyncio.ensure_future(_chat_line(engine, view, line))
        await asyncio.wait({handling, follower}, return_when=asyncio.FIRST_COMPLETED)
        if not handling.done():
            handling.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await handling
            # The send was cut off with no answer, so whether it was recorded is not
            # known (ADR-0293 §4:4): said so, rather than reported either way.
            _print("[yellow]Your last message may or may not have been received.[/]")
            return follower.result()
        if not handling.result():
            return _EXIT_OK


async def _chat_line(engine: AssistantEngine, view: _ChatView, line: str) -> bool:
    """Act on one typed line; ``False`` where it was ``/quit``.

    A blank line sends nothing. A message the type refuses — over the size bound, or
    text with no encoding — is reported and not sent (ADR-0293 §4:7).
    """
    parsed = _parse_chat_line(line)
    match parsed:
        case None:
            return True
        case "quit":
            return False
        case "help":
            _print(_CHAT_HELP)
            return True
        case str():
            _print(f"[yellow]Not sent:[/] {parsed}")
            return True
        case (text, replies_to):
            try:
                message = UserMessage(
                    device_id=view.device_id,
                    message_id=uuid.uuid4().hex,
                    text=text,
                    replies_to=replies_to,
                )
            except ValueError:
                _print(
                    "[yellow]Not sent:[/] a message is at most "
                    f"{TRANSCRIPT_MESSAGE_MAX_CHARS} characters of text."
                )
                return True
            await _send(engine, view, message)
            return True
        case _:  # pragma: no cover — the parse returns one of the shapes above
            assert_never(parsed)


def _parse_chat_line(line: str) -> None | str | tuple[str, int | None]:
    """Read one typed line: nothing, a command, a refusal to say, or a message to send.

    Returns:
        ``None`` for a blank line; ``"quit"`` or ``"help"`` for those commands; a
        ``(text, replies_to)`` pair for a message; any other string is why the line
        was not sent.
    """
    if not line.strip():
        return None
    if line.startswith("//"):
        return (line[1:], None)
    if not line.startswith("/"):
        return (line, None)
    command, _, rest = line[1:].partition(" ")
    if command in {"quit", "exit", "help"}:
        return "help" if command == "help" else "quit"
    if command == "reply":
        return _parse_reply(rest)
    return f"'/{_safe(command)}' is not a command here — '/help' lists them."


def _parse_reply(rest: str) -> str | tuple[str, int]:
    """Read ``/reply``'s message number and text, or say why they cannot be read."""
    number, _, text = rest.strip().partition(" ")
    readable = number.isascii() and number.isdigit() and len(number) <= len(str(_PAGE_BOUND))
    position = int(number) if readable else 0
    if not 1 <= position < _PAGE_BOUND or not text.strip():
        return "'/reply' takes a message number and your text: /reply 3 I meant Pinecrest."
    return (text, position)


async def _send(engine: AssistantEngine, view: _ChatView, message: UserMessage) -> None:
    """Write one message, again with the same id where the first send was lost.

    Sending is safe to repeat (ADR-0293 §4:2): a transport failure leaves it unknown
    whether the conversation recorded the message, and resending the same id is
    recorded once either way. A second failure is raised to the chat's boundary.
    """
    view.sending.add(message.message_id)
    try:
        receipt = await engine.write_message(view.conversation_id, message=message)
    except TransportError:
        receipt = await engine.write_message(view.conversation_id, message=message)
    match receipt.outcome:
        case SendOutcome.RECORDED | SendOutcome.REPEATED:
            _print(f"[dim]  ✓ received, #{receipt.position}[/]")
        case SendOutcome.NOT_AN_END:
            _print(
                "[yellow]Not sent:[/] this device is not one of this conversation's devices "
                "for writing — 'assistant conversation-devices' adds it."
            )
        case SendOutcome.NO_SUCH_REPLY:
            _print(
                f"[yellow]Not sent:[/] this conversation never held a message "
                f"#{message.replies_to} to reply to."
            )
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(receipt.outcome)


async def _follow_chat(engine: AssistantEngine, view: _ChatView, *, retry_seconds: float) -> int:
    """Follow the conversation on the change stream until the chat ends (ADR-0296 §6:1).

    Each stream is opened from the cursor and its chunks applied (:func:`_follow_stream`).
    **Where it is lost** — no hub listening, the connection closed under it, or the
    stream ended because the hub is shutting down — it is opened again from the last
    change applied, which is the device's acknowledgement (§4:4): after
    ``retry_seconds``, then twice as long each time up to
    :data:`_CHAT_RETRY_MAX_SECONDS`, saying once that it was lost and once that it is
    followed again. Lines are still read meanwhile, so ``/quit`` leaves at any time.

    **Only those two transport failures are waited out**, because only they can pass
    by waiting. Every other one — a protocol fault such as a version mismatch, a
    credential refused, an expulsion, a hub that is not the one enrolled at — says
    something about this device or this client that another attempt cannot change,
    so it is raised to the chat's boundary (:func:`_drive_chat`) and rendered there.

    **A refusal for holding no role ends the chat** (ADR-0298 §7:17): the device drops
    every conversation it holds, and this one is the only one a command line holds.
    Every other failure is the boundary's to render as well.

    Returns:
        The chat's exit code, where the conversation ends for this device.
    """
    delay = retry_seconds
    lost = False

    def _opened() -> None:
        nonlocal delay, lost
        if lost:
            _print("[dim]Following the conversation again.[/]")
        delay, lost = retry_seconds, False

    while True:
        try:
            ended = await _follow_stream(engine, view, opened=_opened)
        except HubUnavailableError, ConnectionClosedError:
            ended = None
        except DeviceRefusedError as exc:
            if exc.reason is not DeviceRefusal.NO_ROLE:
                raise
            _print(
                "[yellow]This device holds no role on the hub now, so it is shown no "
                "conversation.[/]"
            )
            return _EXIT_ERROR
        if ended is not None:
            return ended
        if not lost:
            _print("[dim]Lost the hub; following again once it is back…[/]")
            lost = True
        await asyncio.sleep(delay)
        delay = min(delay * 2, _CHAT_RETRY_MAX_SECONDS)


async def _follow_stream(
    engine: AssistantEngine, view: _ChatView, *, opened: Callable[[], None]
) -> int | None:
    """Apply one change stream's chunks from the cursor (ADR-0298 §7).

    A change moves the cursor once it is applied, and only one of this
    conversation's is shown; the hub's own machine is sent every conversation's.
    The current state is shown as it is pushed (ADR-0296 §4:9), and the heartbeat
    moves nothing here.

    **Once the stream has sent its first chunk, and after each roles chunk, the
    conversation is read again** (:func:`_catch_up`), whether it is still shown here
    and its current state with it (§4:9). The state is not this read's to get right:
    the engine's stream sends the state of every conversation the device reads as it
    opens, before any change, and pushes each change after that, so whichever of the
    read and the stream's state is older, the stream's next state corrects it
    (#2740). Over the wire, the first chunk is the device's roles, written as the
    stream opens (ADR-0298 §7:9). **A roles
    chunk is also how a reopening shows itself**: the wire client reopens a stream
    that goes quiet past the dead-peer timeout inside the one iterator (§7:13), and
    the reopened stream starts with the roles again, so reading on every roles
    chunk catches up after a reopening this loop never sees. ``opened`` is called
    once, after the first catch-up.

    Returns:
        The chat's exit code where the conversation ends for this device, or
        ``None`` where the hub ended the stream because it is shutting down, the
        cursor then the one to open the next from.
    """
    caught_up = False
    async with closing_stream(engine.follow_chat(after=view.cursor)) as chunks:
        async for chunk in chunks:
            if isinstance(chunk, ChatStreamEnd):
                view.cursor = max(view.cursor, chunk.next_after)
                return None
            if chunk.change is not None and not await _apply_change(engine, view, chunk.change):
                return _EXIT_OK
            if chunk.state is not None and chunk.state.conversation_id == view.conversation_id:
                view.show_state(chunk.state.state)
            if not caught_up or chunk.roles is not None:
                if not await _catch_up(engine, view):
                    return _EXIT_OK
                if not caught_up:
                    caught_up = True
                    opened()
    return None


async def _apply_change(engine: AssistantEngine, view: _ChatView, change: DeviceChange) -> bool:
    """Apply one change and move the cursor past it; ``False`` where the chat ends.

    A message's replies are resolved before it is shown (:func:`_resolve_replies`),
    and a snapshot travelling with the change is shown before the change itself, as
    the conversation stood at it (ADR-0298 §7:6-§7:7).
    """
    if change.conversation_id == view.conversation_id:
        if change.snapshot is not None:
            await _resolve_replies(engine, view.conversation_id, change.snapshot, into=view.entries)
            view.fill(change.snapshot)
        if isinstance(change.change, MessageAddedChange):
            await _resolve_replies(
                engine, view.conversation_id, (change.change.message,), into=view.entries
            )
    if not view.apply(change.change):
        return False
    view.cursor = change.seq
    return True


async def _catch_up(engine: AssistantEngine, view: _ChatView) -> bool:
    """Read the conversation as a stream opens: whether it is shown, and its state.

    ``False`` where the conversation is gone — deleted, forgotten, or never held by
    a hub that came back with a fresh chat space, which look the same from here on
    purpose (:func:`_render_no_such_conversation`) — or no longer shown to this
    device (ADR-0293 §3:5).
    """
    digest = await engine.conversation(view.conversation_id)
    if digest is None:
        _render_no_such_conversation(view.conversation_id)
        return False
    if not view.still_shown(digest.devices):
        return False
    view.show_state(digest.state)
    return True


async def _drive_start_conversation(engine: AssistantEngine) -> int:
    """Start an empty conversation and say where it is shown (ADR-0293 §2:1, §3:1)."""
    started = await engine.start_conversation()
    digest = await engine.conversation(started.id)
    _print(f"[green]Started a conversation:[/] [bold cyan]{_safe(started.id)}[/]")
    devices = () if digest is None else digest.devices
    if devices:
        _print("  [dim]Shown on:[/]")
        _render_device_set(devices)
    else:
        _print(
            "  [yellow]It is shown on no device:[/] your devices are empty. "
            "'assistant my-devices --add' adds one."
        )
    _print_chat_hint(started.id)
    return _EXIT_OK


async def _drive_show_conversation(
    engine: AssistantEngine, conversation_id: str, *, before: int | None, limit: int
) -> int:
    """Show one conversation's devices, current state and a page of its messages."""
    digest = await engine.conversation(conversation_id)
    page = (
        None
        if digest is None
        else await engine.transcript(conversation_id, before=before, limit=limit)
    )
    if digest is None or page is None:
        _render_no_such_conversation(conversation_id)
        return _EXIT_ERROR
    _print(f"[bold cyan]{_safe(digest.id)}[/]")
    _print(f"  [dim]Started:[/] {_when(digest.started_at)}")
    if digest.devices:
        _print("  [dim]Shown on:[/]")
        _render_device_set(digest.devices)
    else:
        _print("  [dim]Shown on no device.[/]")
    view = _ChatView(digest.id, device_id="", cursor=page.as_of)
    await _resolve_replies(engine, digest.id, page.entries, into=view.entries)
    view.show_state(digest.state)
    _print("")
    view.show_page(page)
    return _EXIT_OK


async def _drive_stop(engine: AssistantEngine, activation_id: str) -> int:
    """Relay one stop and print what the answer means (ADR-0297 §5:8).

    One engine call and one fixed sentence per :class:`ActivationStop` member; the
    exit code is :data:`_STOP_EXIT_CODES`'. A failure to reach the hub is the caller's
    (:func:`_with_engine`), so it is rendered and exits non-zero rather than escaping.
    """
    answer = await engine.stop_activation(activation_id)
    _print(_STOP_PHRASES[answer])
    return _STOP_EXIT_CODES[answer]


async def _drive_delete_message(
    engine: AssistantEngine, conversation_id: str, position: int, *, confirm: Callable[[], bool]
) -> int:
    """Show the message, take the answer, then delete it alone (ADR-0293 §5:8, §5:9).

    The message is read first so the person deletes what they were shown
    (ADR-0073 §5); a number naming no standing message is reported and nothing is
    asked.
    """
    below = position + 1 if position + 1 < _PAGE_BOUND else None
    page = await engine.transcript(conversation_id, before=below, limit=1)
    if page is None:
        _render_no_such_conversation(conversation_id)
        return _EXIT_ERROR
    entry = page.entries[-1] if page.entries else None
    if not isinstance(entry, TranscriptMessage) or entry.position != position:
        _print(
            f"[yellow]Nothing to delete:[/] that conversation holds no message #{position} — "
            "it was never written there, or it is deleted already."
        )
        return _EXIT_ERROR
    known: dict[int, TranscriptMessage | DeletedMessage] = {}
    await _resolve_replies(engine, conversation_id, (entry,), into=known)
    _print("\n[bold yellow]About to delete this message[/]")
    _render_chat_entry(entry, known=known)
    _print(
        "\n  [yellow]It is removed from the conversation on every device, and a reply to "
        "it stays, naming a deleted message. The assistant's memory is not changed: what "
        "it took in from this message stays until you forget the conversation.[/]"
    )
    if not confirm():
        _print("[dim]Left alone. Nothing was deleted.[/]")
        return _EXIT_OK
    if not await engine.delete_message(conversation_id, position=position):
        _print(f"[yellow]Nothing deleted:[/] message #{position} was already gone.")
        return _EXIT_ERROR
    _print(f"[green]Deleted[/] message #{position}.")
    return _EXIT_OK


async def _drive_delete_conversation(
    engine: AssistantEngine, conversation_id: str, *, confirm: Callable[[], bool]
) -> int:
    """Show the conversation, take the answer, then delete it, forgetting nothing (§2:3).

    Deleting and forgetting are offered side by side and never as one act (§2:7):
    the prompt and the outcome both name ``forget-conversation`` as the other one.
    """
    digest = await engine.conversation(conversation_id)
    if digest is None:
        _render_no_such_conversation(conversation_id)
        return _EXIT_ERROR
    _print("\n[bold yellow]About to delete this conversation[/]")
    _print(f"  [bold cyan]{_safe(digest.id)}[/]")
    _print(f"  [dim]Started:[/] {_when(digest.started_at)}")
    _print(
        "\n  [yellow]Deleting removes the conversation and all its messages, on every "
        "device. It forgets nothing: what the assistant remembers of it stays until you "
        "forget it, which you can do before or after deleting.[/]"
    )
    _print_forget_hint(digest.id)
    if not confirm():
        _print("[dim]Left alone. Nothing was deleted.[/]")
        return _EXIT_OK
    if not await engine.delete_conversation(digest.id):
        _print("[yellow]Nothing to delete:[/] that conversation was already deleted.")
        return _EXIT_ERROR
    _print("[green]Deleted.[/] The assistant's memory of it is unchanged.")
    _print_forget_hint(digest.id)
    return _EXIT_OK


async def _drive_devices(
    engine: AssistantEngine,
    conversation_id: str | None,
    change: _DeviceChange,
    *,
    confirm: Callable[[], bool],
) -> int:
    """Show "my devices" or a conversation's devices, or change them (ADR-0293 §3).

    The set is read, changed as asked and written back whole, which is how the
    surface takes it — so two people changing one set at once keep the later write.
    Adding is the user's statement that the device's screen is private (§3:2, §3:3),
    shown before it is asked.
    """
    current = await _read_devices(engine, conversation_id)
    if current is None:
        _render_no_such_conversation(conversation_id or "")
        return _EXIT_ERROR
    if change.empty:
        _render_devices_heading(conversation_id, current)
        return _EXIT_OK
    for missing in sorted(set(change.remove) - {one.device_id for one in current}):
        _print(f"[dim]{_safe(missing)} was not one of them.[/]")
    kept = tuple(one for one in current if one.device_id not in change.remove)
    wanted = _with_devices(kept, change.add)
    if wanted is None:
        _render_devices_full()
        return _EXIT_ERROR
    if change.add:
        _render_device_statement(conversation_id)
        if not confirm():
            _print("[dim]Left alone. Nothing was changed.[/]")
            return _EXIT_OK
    if conversation_id is None:
        await engine.set_my_devices(wanted)
    else:
        await engine.set_conversation_devices(conversation_id, devices=wanted)
    now = await _read_devices(engine, conversation_id)
    _render_devices_heading(conversation_id, now or ())
    if conversation_id is None:
        _print(
            "[dim]A conversation already started keeps its own devices — "
            "'assistant conversation-devices' changes one.[/]"
        )
    return _EXIT_OK


async def _read_devices(
    engine: AssistantEngine, conversation_id: str | None
) -> tuple[ChatDevice, ...] | None:
    """Read "my devices", or a conversation's devices; ``None`` where it is gone."""
    if conversation_id is None:
        return await engine.my_devices()
    digest = await engine.conversation(conversation_id)
    return None if digest is None else digest.devices


def _with_devices(
    devices: Sequence[ChatDevice], added: Sequence[ChatDevice]
) -> tuple[ChatDevice, ...] | None:
    """``devices`` with ``added`` in, replacing a device's access; ``None`` past the bound."""
    named = {one.device_id for one in added}
    merged = (*(one for one in devices if one.device_id not in named), *added)
    if len(merged) > CHAT_DEVICES_MAX:
        return None
    return tuple(sorted(merged, key=lambda one: one.device_id))


async def _resolve_replies(
    engine: AssistantEngine,
    conversation_id: str,
    entries: Sequence[TranscriptMessage | DeletedMessage],
    *,
    into: dict[int, TranscriptMessage | DeletedMessage],
) -> None:
    """Read each message ``entries`` reply to that is neither among them nor known.

    A reply's reference names a deleted message, shown as such (ADR-0293 §5:8), and
    that holds where the deleted message is older than the page being shown — so its
    entry is read, one per distinct message, and kept beside the ones shown.
    """
    present = {one.position for one in entries} | set(into)
    wanted = sorted(
        {
            one.replies_to
            for one in entries
            if isinstance(one, TranscriptMessage)
            and one.conversation_id == conversation_id
            and one.replies_to is not None
            and one.replies_to not in present
        }
    )
    for target in wanted:
        # A reply names an earlier message, so `target + 1` is a position too.
        page = await engine.transcript(conversation_id, before=target + 1, limit=1)
        if page is not None and page.entries and page.entries[-1].position == target:
            into[target] = page.entries[-1]


def _reads_and_writes(devices: Sequence[ChatDevice], device_id: str) -> bool:
    """Whether ``device_id`` is among ``devices`` as an end for both (ADR-0293 §3:5)."""
    return any(
        one.device_id == device_id and one.access is DeviceAccess.READ_WRITE for one in devices
    )


def _render_chat_entry(
    entry: TranscriptMessage | DeletedMessage,
    *,
    known: Mapping[int, TranscriptMessage | DeletedMessage],
) -> None:
    """Render one transcript entry: who wrote it, when, what it replies to, its text.

    A deleted message is its marker, with no text (ADR-0293 §5:12), and a reply to
    one says so (§5:8). A message cut off before it finished is said never to be a
    complete answer (§5:2). The text is a block of its own behind
    :func:`_render_content`'s gutter, so a line inside it cannot pass for a header.
    """
    if isinstance(entry, DeletedMessage):
        _print(f"[dim]#{entry.position} · deleted[/]")
        return
    if entry.author is MessageAuthor.USER:
        who = f"[bold]You[/] [dim](from {_safe(entry.device_id or '')})[/]"
    else:
        who = "[bold cyan]Assistant[/]"
    head = f"[dim]#{entry.position}[/] {who} [dim]· {_when(entry.written_at)}"
    if entry.replies_to is not None:
        gone = isinstance(known.get(entry.replies_to), DeletedMessage)
        head += f" · replying to #{entry.replies_to}{', a deleted message' if gone else ''}"
    _print(f"{head}[/]")
    _render_content(entry.text)
    if entry.options:
        _print("  [dim]Options:[/] " + " | ".join(_safe(option) for option in entry.options))
    if entry.cut_off:
        _print("  [yellow]Cut off before it finished — not a complete answer.[/]")


def _render_device_set(devices: Sequence[ChatDevice]) -> None:
    """One line per device: its id and what it may do (ADR-0293 §3:5)."""
    for one in devices:
        _print(f"    {_safe(one.device_id)} [dim]— {_ACCESS_PHRASES[one.access]}[/]")


def _render_devices_heading(conversation_id: str | None, devices: Sequence[ChatDevice]) -> None:
    """Name the set, then its devices, or say it is empty."""
    if conversation_id is None:
        title = "Your devices — every new conversation is shown on them"
    else:
        title = f"The devices of conversation {_safe(conversation_id)}"
    if not devices:
        _print(f"[bold]{title}:[/] none.")
        return
    _print(f"[bold]{title}:[/]")
    _render_device_set(devices)


def _render_device_statement(conversation_id: str | None) -> None:
    """What adding a device says, before it is asked (ADR-0293 §3:2, §3:3)."""
    if conversation_id is None:
        _print(
            "  [yellow]Adding a device to your devices says its screen is private: every "
            "conversation started from now on is shown on it.[/]"
        )
    else:
        _print(
            "  [yellow]Adding a device to this conversation says its screen is private, "
            "for this conversation: it is shown there.[/]"
        )


def _render_devices_full() -> None:
    """Say a set of devices is at its bound, so nothing was added."""
    _print(
        f"[yellow]Nothing added:[/] a set of devices holds at most {CHAT_DEVICES_MAX}; "
        "remove one first."
    )


def _print_stop_hint(state: ConversationState) -> None:
    """Say how to stop each running activation the state names (ADR-0297 §5:7).

    The ids are the current state's and only the current state's (ADR-0295 §1:2): this
    command line holds no running activation of its own to name. The state names every
    running activation started from the conversation (ADR-0349 §10:3), so one command is
    offered for each, in the state's order, each naming exactly one activation as
    ADR-0297 §5's ``assistant stop <activation-id>`` does. Where the state shows
    "working…" with no id, nothing is said — that activation cannot be stopped, which is
    ADR-0297 §5's residual of a failed id factory, and offering a command it would only
    refuse would be worse than silence.
    """
    ids = tuple(dict.fromkeys(state.activation_ids))
    if not ids:
        return
    if len(ids) == 1:
        _print(f"[dim]To stop it: assistant stop {_safe(ids[0])}[/]")
        return
    _print("[dim]To stop them, run each of these:[/]")
    for activation_id in ids:
        _print(f"[dim]  assistant stop {_safe(activation_id)}[/]")


def _print_chat_hint(conversation_id: str) -> None:
    """Offer the command that opens a conversation, where its id can be shown."""
    if _is_pasteable(conversation_id):
        _print_hint(f"[dim]Open it with: assistant chat -c {_argument(conversation_id)}[/]")
    else:
        _print(_uncopyable("Its id"))


def _print_forget_hint(conversation_id: str) -> None:
    """Name forgetting beside deleting, as the other act (ADR-0293 §2:7)."""
    if _is_pasteable(conversation_id):
        _print_hint(
            f"[dim]  To forget it: assistant forget-conversation {_argument(conversation_id)}[/]"
        )
    else:
        _print(_uncopyable("Its id", "'assistant forget-conversation' still takes it."))


def _confirm_device_statement() -> bool:
    """Read the yes/no for adding a device; what it says was already shown. Defaults no."""
    return typer.confirm("Add it?", default=False)


def _confirm_delete_message() -> bool:
    """Read the yes/no for deleting a message already shown. Defaults no."""
    return typer.confirm("Delete it?", default=False)


def _confirm_delete_conversation() -> bool:
    """Read the yes/no for deleting a conversation already shown. Defaults no."""
    return typer.confirm("Delete it?", default=False)


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
    # empty both become "every band", and for --kind "memories alone", the engine's
    # default (ADR-0328 §11:2). `--kind episodic` still lists episodes (ADR-0074 §6).
    code = asyncio.run(
        _list_beliefs(bands=band or None, kinds=kind or None, limit=limit, offset=offset)
    )
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
    rather than lose it, correct me in ``assistant chat`` by replying to what I got
    wrong.
    """
    code = asyncio.run(_forget_belief(belief_id, assume_yes=yes))
    raise typer.Exit(code)


# --- the person model: what the About you panel shows (ADR-0338 §8:1-§8:3) -----------
#
# The command line's half of the About you panel, for a person without a browser: the
# same eight members, read and written as the page reads and writes them, in the page's
# words (`person_inspection`). The person is the hub's one person, the owner (§2:1), so
# no command takes one. Shown only to the person and the owner (§8:3): the hub refuses
# a device without the commands role, and that refusal is rendered as every other.

about_app = typer.Typer(
    name="about",
    help=(
        "What I know about you and keep in mind: your profile's five fields, the log of "
        "changes to them, the memories you pinned, how you like me to speak, and my "
        "suggestions. The same as the page's About you panel."
    ),
    no_args_is_help=True,
)
app.add_typer(about_app, name="about")


def _present_person_record(value: str) -> str:
    """Reject a blank or unwritable id of the person model, **without stripping** it.

    The person model holds every id verbatim and a pointer that normalised what it was
    handed could name another record (ADR-0338 §10:4), so this is
    :func:`_present_id`'s check minus its strip.

    Args:
        value: The id as the user typed it.

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


def _present_profile_value(value: str) -> str:
    """Reject a field's value with no UTF-8 encoding, **without changing** it.

    ``set_profile_field`` refuses such a value with a ``ValueError`` before any I/O
    (``profile_value``), which is not an :class:`AssistantError` and would escape
    :func:`_about`'s error boundary as a traceback (ADR-0042 §7; adversarial review,
    round 8). Every other rule on a value is the store's, said as its refusal, so a
    blank value is not refused here.

    Args:
        value: The value as the user typed it.

    Returns:
        The value, byte for byte.

    Raises:
        BadParameter: If the value has no UTF-8 encoding.
    """
    try:
        encodable_text(value)
    except ValueError as exc:
        msg = "must be text with a UTF-8 encoding"
        raise typer.BadParameter(msg) from exc
    return value


_ABOUT_LIMIT_OPTION = typer.Option(
    25, "--limit", callback=_page_argument, help="How many of each list to show at most."
)
_ABOUT_OFFSET_OPTION = typer.Option(
    0, "--offset", callback=_page_argument, help="How many of each list to skip first."
)
_ABOUT_FIELD_ARGUMENT = typer.Argument(..., help="Which of the five fields.")
_ABOUT_MEMORY_ARGUMENT = typer.Argument(
    ...,
    callback=_present_person_record,
    help="The memory, by the id 'assistant beliefs' or 'assistant about show' shows.",
)


async def _about(read: Callable[[AssistantEngine], Awaitable[int]], *, off_is_ok: bool) -> int:
    """Open the engine, run one person-model act, and render a hub with the switch off.

    One error boundary (ADR-0042 §7). ``PersonModelOffError`` is a state rather than a
    fault, so it is said in the panel's words and never as an error: a read exits 0, a
    write, which did nothing, does not.
    """
    try:
        engine = await _open_engine()
        return await read(engine)
    except PersonModelOffError:
        person_inspection.render_off(console)
        return _EXIT_OK if off_is_ok else _EXIT_ERROR
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR


def _about_written(act: str, edit: PersonModelEdit) -> int:
    """Say what a write did, and exit non-zero where it was refused."""
    done, said = person_inspection.edit_text(act, edit)
    person_inspection.render_said(console, said)
    return _EXIT_OK if done else _EXIT_ERROR


@about_app.command("show")
def about_show(
    limit: int = _ABOUT_LIMIT_OPTION,
    offset: int = _ABOUT_OFFSET_OPTION,
) -> None:
    """Show your profile, what I keep in mind, how you like me to speak, and my suggestions.

    Each list is paged by --limit and --offset together, and says how many it holds,
    so a list longer than a page is read with a larger --offset. The ids shown are the
    ones the commands below take.
    """

    async def read(engine: AssistantEngine) -> int:
        view = await engine.person_model(OWNER_PERSON_ID, limit=limit, offset=offset)
        if view is None:
            person_inspection.render_said(console, person_inspection.NO_PROFILE)
            return _EXIT_ERROR
        person_inspection.render_model(console, view, offset=offset)
        return _EXIT_OK

    raise typer.Exit(asyncio.run(_about(read, off_is_ok=True)))


@about_app.command("log")
def about_log(
    limit: int = _ABOUT_LIMIT_OPTION,
    offset: int = _ABOUT_OFFSET_OPTION,
) -> None:
    """Show the log of changes to your profile, the most recent first."""

    async def read(engine: AssistantEngine) -> int:
        page = await engine.profile_changes(OWNER_PERSON_ID, limit=limit, offset=offset)
        person_inspection.render_changes(console, page, full=bool(page) and len(page) == limit)
        return _EXIT_OK

    raise typer.Exit(asyncio.run(_about(read, off_is_ok=True)))


@about_app.command("set")
def about_set(
    field: ProfileField = _ABOUT_FIELD_ARGUMENT,
    value: str = typer.Argument(
        ..., callback=_present_profile_value, help="Its new value, as you want it kept."
    ),
) -> None:
    """Set one of your profile's fields. A time zone is a name such as Europe/Lisbon.

    The value is kept exactly as typed, and checked by the hub: a time zone it cannot
    resolve, or a value past its length, is refused and nothing is changed.
    """

    async def write(engine: AssistantEngine) -> int:
        edit = await engine.set_profile_field(OWNER_PERSON_ID, field=field, value=value)
        return _about_written("set", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


@about_app.command("clear")
def about_clear(field: ProfileField = _ABOUT_FIELD_ARGUMENT) -> None:
    """Clear one of your profile's fields, so it is not set."""

    async def write(engine: AssistantEngine) -> int:
        edit = await engine.set_profile_field(OWNER_PERSON_ID, field=field)
        return _about_written("clear", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


@about_app.command("pin")
def about_pin(
    memory_id: str = _ABOUT_MEMORY_ARGUMENT,
    *,
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the prompt. The wording is still shown first."
    ),
) -> None:
    """Pin a memory, so I keep it in mind in every conversation.

    Pinning confirms the wording shown as yours (ADR-0338 §4:3), so the memory is
    shown first and pinned once you agree; --yes skips the question, not the showing.
    """
    confirm: Callable[[], bool] = (lambda: True) if yes else _confirm_pin

    async def write(engine: AssistantEngine) -> int:
        held = await engine.belief(memory_id)
        # The wording shown is the wording the pin confirms (ADR-0338 §4:3), so the read
        # must be of the very memory the pin names. The belief read normalises an id and
        # the pin does not (§10:4), so a read that answered for another id than the one
        # typed is refused before anything is shown or asked.
        if held is None or held.id != memory_id:
            person_inspection.render_no_memory(console, memory_id)
            return _EXIT_ERROR
        person_inspection.render_pin_prompt(console, held.content)
        if not confirm():
            _print("[dim]Left alone. Nothing was pinned.[/]")
            return _EXIT_OK
        edit = await engine.pin_memory(OWNER_PERSON_ID, memory_id=memory_id)
        return _about_written("pin", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


def _confirm_pin() -> bool:
    """Read the yes/no for a pin whose wording was already shown. Defaults no."""
    return typer.confirm("Pin it?", default=False)


@about_app.command("unpin")
def about_unpin(memory_id: str = _ABOUT_MEMORY_ARGUMENT) -> None:
    """Unpin a memory. The memory itself is kept; forgetting it is 'assistant forget'."""

    async def write(engine: AssistantEngine) -> int:
        edit = await engine.unpin_memory(OWNER_PERSON_ID, memory_id=memory_id)
        return _about_written("unpin", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


@about_app.command("remove-style")
def about_remove_style(
    mark_id: str = typer.Argument(
        ...,
        callback=_present_person_record,
        help="The style memory's mark, by the id 'assistant about show' shows.",
    ),
) -> None:
    """Stop keeping a memory in mind as how you like me to speak; I will not mark it again."""

    async def write(engine: AssistantEngine) -> int:
        edit = await engine.remove_style_mark(OWNER_PERSON_ID, mark_id=mark_id)
        return _about_written("unmark", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


_ABOUT_SUGGESTION_ARGUMENT = typer.Argument(
    ...,
    callback=_present_person_record,
    help="The suggestion, by the id 'assistant about show' shows.",
)


@about_app.command("accept")
def about_accept(suggestion_id: str = _ABOUT_SUGGESTION_ARGUMENT) -> None:
    """Accept one of my suggestions: set its field, or pin its memory, which confirms it."""

    async def write(engine: AssistantEngine) -> int:
        edit = await engine.accept_person_suggestion(OWNER_PERSON_ID, suggestion_id=suggestion_id)
        return _about_written("accept", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


@about_app.command("dismiss")
def about_dismiss(suggestion_id: str = _ABOUT_SUGGESTION_ARGUMENT) -> None:
    """Dismiss one of my suggestions, so I do not suggest it again."""

    async def write(engine: AssistantEngine) -> int:
        edit = await engine.dismiss_person_suggestion(OWNER_PERSON_ID, suggestion_id=suggestion_id)
        return _about_written("dismiss", edit)

    raise typer.Exit(asyncio.run(_about(write, off_is_ok=False)))


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

    ``--scope notify`` lets me read it in order to raise things with you
    unprompted — it is permission to *read*, not a promise that anything arrives.

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


@app.command("connect-keyless")
def connect_keyless(
    identity: str = typer.Argument(
        ...,
        metavar="NAME",
        callback=_present_identity,
        help="The name you give the source, as you recognise it — for example Open-Meteo.",
    ),
) -> None:
    """Connect a source that needs no key, such as a weather service.

    **A source that needs a key, a token or a password uses 'assistant connect'
    instead.** This command never asks for a credential and takes none, so use it
    only for a source that has none to give.

    The name is yours to choose, and I record it exactly as you typed it and show it
    back to you. The reference is minted here, as on ``connect``, and
    ``assistant connections`` is where you read it back.

    **This is not 'assistant grant'.** A connection authorises nothing.
    """
    code = asyncio.run(_connect_keyless_account(identity))
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

    **A refusal, not a failed stream** (#1940). An ``OSError`` from the descriptor
    itself — a stream that errors mid-read, a pipe whose peer died as ``EIO``, a
    controlling terminal ``getpass`` cannot open — is a statement about the *read*
    and about nothing else: nothing arrived, so nothing about a value is known.
    Every surface that takes a credential now catches it — here, and in
    :func:`_drive_connect` and :func:`_drive_reconnect` — and all three render it
    the one way this boundary already renders every failure it catches,
    :func:`_render_error`'s "Error:", carrying the errno the platform gave.

    **The other rendering is refused, and by the same reasoning that chose this
    one.** :func:`_render_unusable_credential` says a credential cannot be used,
    which asserts something about a value that was never read, and its safety rests
    on ADR-0125 §6 governing what a *refusal of a value* may say — a guarantee that
    has nothing to reach when the refusal is the stream's. A third sentence of its
    own was available and is not taken: #1146 spent a change removing exactly this
    surface's per-command divergence, and one failed read means one thing at all
    three commands.
    """
    try:
        credential = read_credential()
        settings = load_settings()
        configure_logging(settings)
        await store_enrolment(
            _enrolment_secrets(settings), hub_identity=hub_identity, credential=credential
        )
    except (AssistantError, TransportError, ValueError, OSError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _print(f"[green]Enrolled.[/] This device is now bound to hub {_safe(hub_identity)}.")
    _print(
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
        _print("This device held no enrolment; nothing changed.")
        return _EXIT_OK
    _print("[green]Removed[/] the credential and the hub identity from this machine's keyring.")
    _print(
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

    **A fault exits by ADR-0083 §5's table, the hub's own** (#3167):
    ``78`` where restarting unchanged never succeeds — a setting it refused, an
    edge key that will not load, a hosted address this machine does not hold, a
    file or port the operating system will not give it — and ``1`` for everything
    that may clear. Without the distinction a supervisor restarts a gateway that
    refused a setting until somebody notices, which is §5's "crash loop wearing a
    diagnosis". :func:`~ai_assistant.interfaces.gateway.exits.exit_code` reads the
    verdict the refusal was raised with, and a ``78`` says, after the cause, that it
    stays down and what ends that.

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
        code = gateway_exits.exit_code(exc)
        if code == gateway_exits.EXIT_DEPLOYMENT:
            # ADR-0083 §5: "every `78` prints its cause and the operator action". The
            # cause is the line above; this is what ends the refusal, in words that
            # carry nothing but the code (ADR-0004 §5).
            _print(
                f"[red]The gateway stays down (exit {code}):[/] it would refuse the same "
                f"way at every start. Change what the line above names, then start it "
                f"again."
            )
        return code
    except KeyboardInterrupt, asyncio.CancelledError:
        _print("[dim]Gateway stopped. Every session ended with it.[/]")
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
            ``OSError`` from a standard output that will not take the value — and
            it is a :class:`~.gateway.exits.ClearableRefusalError` wherever the
            errno is one a restart can get past (see :func:`_gateway_did_not_start`).
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

    **Which of ADR-0083 §5's codes it earns is the errno's to say** (#3167), and only
    the few that mean the operating system will not let this process do this — an
    unreadable bundle, a port below 1024 this user may not bind — are the stay-down
    ``78`` (:func:`~.gateway.exits.stays_down`). A taken port is a ``1``, because
    whatever holds it is serving or stopping, as a contended hub lock is (ADR-0083
    §1); every other errno is a ``1`` by §5's tie-break. Each ``1`` is raised as
    :class:`~.gateway.exits.ClearableRefusalError`, which says so.

    Args:
        exc: What the start raised.
        port: ``gateway_port``, named only where the errno is about a port.
        probes_an_address: Whether a remote browser listener is configured, and so
            whether an ephemeral bind of its own is in the path.

    Returns:
        The error :func:`_serve_gateway`'s boundary renders and exits non-zero on: a
        plain ``ConfigurationError`` where the errno stays down, and a
        :class:`~.gateway.exits.ClearableRefusalError` everywhere else.
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
    return (
        ConfigurationError(msg)
        if gateway_exits.stays_down(exc)
        else gateway_exits.ClearableRefusalError(msg)
    )


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
        _print(f"[yellow]{_GATEWAY_NOTES[note]}[/]")


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

    **The origin line makes no claim about a live listener, and that is the point
    of the wording.** ``run_gateway`` discloses *before* it serves — ADR-0182 §1
    says so of the disposition it installs "before any disclosure names the act",
    and ADR-0168 §5's "a gateway that cannot disclose its bootstrap value does not
    start" puts the disclosure ahead of the bind by construction. So on a failed
    bind the owner used to read "listening on http://…" one line above the error
    saying the port could not be bound: a claim about a listener that did not exist
    and, in that run, never would (#1460). Naming the address the gateway is *for*
    is true when it is written and just as useful to paste. Neither ADR constrains
    the verb; both constrain what the disclosure must name, and §1's four — the
    value, the origins, the count and the act — are all still here.

    Args:
        disclosure: The value, the origins, the advisory count and the act.

    Raises:
        ConfigurationError: If standard output cannot be written. A
            :class:`~.gateway.exits.ClearableRefusalError` unless the errno is one
            no restart changes, for the reason :func:`_gateway_did_not_start`
            gives: a stream that refused a write is most often a reader that went
            away, and the next start is handed a new one (#3167).
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
            f"Assistant gateway at {', '.join(disclosure.origins)}\n"
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
        if gateway_exits.stays_down(exc):
            raise ConfigurationError(msg) from exc
        raise gateway_exits.ClearableRefusalError(msg) from exc


async def _list_conversations(*, limit: int, offset: int) -> int:
    """Load settings, build the engine, list conversations, and close it (ADR-0074 §2).

    One error boundary (ADR-0042 §7). The paging arguments were already checked against the store's
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
    confirm: Callable[[ConversationDigest | None], bool] = (
        (lambda _digest: True) if assume_yes else _confirm_forget_conversation
    )
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_forget_conversation(engine, conversation_id, confirm=confirm)


async def _list_beliefs(
    *,
    bands: list[BeliefBand] | None,
    kinds: list[MemoryKind] | None,
    limit: int,
    offset: int,
) -> int:
    """Load settings, build the engine, list the beliefs, and close it (ADR-0073 §7).

    One error boundary spans every stage
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

    One error boundary (ADR-0042 §7). The paging arguments were already checked against
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

    **No show-then-confirm ceremony.** A held notification is not a belief of any band,
    so ADR-0073 §5's requirement to render before destroying does not reach it — and a
    dismissal destroys nothing at all: the record stays readable and stays in the export
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
    ``forget_question`` takes" — a question is not a belief, so nothing is being
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
        OSError: If the terminal itself fails — ``getpass`` opens ``/dev/tty`` and
            reads from it, and neither is guaranteed to succeed. Nothing was read,
            so it is not a refusal; every caller renders it as the failed read it
            is (:func:`_store_device_enrolment`, #1940).
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
        OSError: If the descriptor itself fails — a stream that errors mid-read, a
            pipe whose peer died in a way the platform reports as ``EIO``, a closed
            stream. Nothing was read, so it is not a refusal; every caller renders
            it as the failed read it is (:func:`_store_device_enrolment`, #1940).
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


async def _connect_keyless_account(identity: str) -> int:
    """Show the name, refuse it locally if it is unusable, obtain a client, and connect.

    **The name's refusals run before any I/O** (ADR-0325 §4:3), and here that is
    stronger than :func:`_connect_account`'s ordering: there is no credential to
    ask for, so nothing is gained by reaching the hub first, and a name the act
    could never record is refused before settings are loaded or a socket is dialled.
    The check is :func:`~ai_assistant.wire.codec.usable_identity` with no
    credential to compare against, the one the wire client itself runs before its
    socket is opened — so this refuses exactly what the client would, a step
    earlier, and nothing more.

    **It is reached only by its own command** (ADR-0325 §4:4): nothing on the
    credentialed path calls it, offers it, or falls back to it when a credential
    is missing, blank or refused.
    """
    _render_keyless_intent(identity)
    try:
        usable_identity(identity, credential=None)
    except UnusableIdentityError as exc:
        _render_refused_keyless_name(exc)
        return _EXIT_ERROR
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_connect_keyless(engine, identity)


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

    One error boundary (ADR-0042 §7). ``--yes`` supplies the answer but not the
    rendering: the belief is displayed either way, because a person cannot consent to
    destroying something they were not shown and a non-interactive approval must not
    destroy what the user never saw (ADR-0073 §5, ADR-0052 §4).
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
            _print("[dim]Left alone. Nothing was forgotten.[/]")
            return _EXIT_OK
        destroyed = await engine.forget(belief.id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        _print("[yellow]Nothing to forget:[/] that belief was already gone.")
        return _EXIT_ERROR
    _print("[green]Forgotten.[/] That belief is destroyed — it is in no export.")
    return _EXIT_OK


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
    engine: AssistantEngine,
    conversation_id: str,
    *,
    confirm: Callable[[ConversationDigest | None], bool],
) -> int:
    """Show the conversation's count and span, take the answer, then forget its episodes.

    Memory-only since ADR-0293 §11:4: the conversation and its transcript stay.

    Show-then-confirm at the unit the user thinks in (ADR-0074 §8, ADR-0073 §5).
    A refusal is a valid outcome and exits 0. **An id naming no conversation this
    surface can show is still offered**, because forgetting reaches the episodes on
    the conversation's place whether or not the conversation still stands (ADR-0293
    §2:5) — deleting one first and forgetting it after is the order
    ``delete-conversation`` offers. Unknown and deleted are said the same way, and
    where nothing was held the outcome says so and exits non-zero.
    """
    try:
        digest = await engine.conversation(conversation_id)
        if digest is None:
            _render_forget_unseen_conversation_prompt(conversation_id)
        else:
            _render_forget_conversation_prompt(digest)
        if not confirm(digest):
            _print("[dim]Left alone. Nothing was forgotten.[/]")
            return _EXIT_OK
        destroyed = await engine.forget_conversation(conversation_id)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    if not destroyed:
        _print(
            "[yellow]Nothing to forget:[/] the assistant's memory held nothing from that "
            "conversation."
        )
        return _EXIT_ERROR
    _print(
        "[green]Forgotten.[/] The assistant no longer recalls that conversation anywhere "
        "else. The conversation and its transcript stay; only deleting removes them."
    )
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
            _print("[dim]Left alone. Nothing was granted.[/]")
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
        _print(
            "[yellow]Nothing to withdraw:[/] no live grant covers that source. "
            "(That is about the grant, not about any read — see 'assistant grants' "
            "for what was granted and withdrawn.)"
        )
        return _EXIT_ERROR
    _print(
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
        _print("[dim]Left alone. Nothing was withdrawn and nothing was granted.[/]")
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
        _print(
            "[yellow]Nothing to dismiss:[/] no notification with that id is still "
            "outstanding. It may never have existed, or it may already have been "
            "dismissed, expired, or ruled out — 'assistant notifications' lists what "
            "I am holding."
        )
        return _EXIT_ERROR
    _print(
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
        _print("[yellow]Nothing to forget:[/] no notification has that id.")
        return _EXIT_ERROR
    _print(
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
    _print("[green]Tuned.[/] These are the settings in force now.\n")
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
    except OSError as exc:
        # A failed read is not a refused value, and the two do not share a sentence:
        # :func:`_store_device_enrolment` holds the reasoning for all three surfaces
        # and this is the rendering it settles on (#1940).
        _render_error(exc)
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


async def _drive_connect_keyless(engine: AssistantEngine, identity: str) -> int:
    """Connect a source that needs no credential, and report the outcome (ADR-0325 §3).

    :func:`_drive_connect` with no credential to take, so with one fewer step and
    fewer outcomes. The act is one write under a reference it mints (§3:2, §3:4), so
    of ADR-0151 §7's partial classes only the not-known one is reachable: a
    :class:`~ai_assistant.core.errors.ConnectionStoreError` carries no reference,
    and the client says so and points at ``connected_accounts`` rather than reading
    or re-running anything (§3:6). The identity's refusal is
    :func:`_connect_keyless_account`'s, already run; one raised here anyway is
    rendered in the same words.
    """
    try:
        connected = await engine.connect_keyless_account(identity=identity)
    except asyncio.CancelledError:
        # :func:`_drive_connect`'s arm, for ADR-0151 §7's cancellation clause.
        _render_cancelled_act("keyless connection")
        _render_connections_unread()
        raise
    except UnusableIdentityError as exc:
        _render_refused_keyless_name(exc)
        return _EXIT_ERROR
    except (AssistantError, TransportError) as exc:
        return await _report_provisioning_failure(engine, "keyless connection", exc, reference=None)
    _render_keyless_connected(connected)
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
    except OSError as exc:
        # :func:`_drive_connect`'s arm, for :func:`_store_device_enrolment`'s reason
        # (#1940).
        _render_error(exc)
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
        _print(
            "\n[dim]That class was already reaching you exactly that far in the settings "
            "I read, so this asked for no change to it.[/]"
        )
    elif asked.reach is NotificationReach.INTERRUPT:
        _print(
            "\n[dim]Anything of that class I am already holding is now due to be "
            "looked at again, on my next sweep rather than this instant — so one that "
            "named a moment it stops mattering can reach you without waiting for the "
            "next such notification. One that named no such moment stays held however "
            "long you wait: no reach setting makes it urgent.[/]"
        )
    elif asked.reach is NotificationReach.OFF:
        _print(
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


#: The marker every display line after a printed line's first one carries
#: (:func:`_print`). No line this adapter authors begins with it — a field leads with
#: its label, a listing row with its own indent, a citation with ``-`` — so a
#: continuation can never be read as a line this adapter wrote fresh.
#:
#: The shape is the same one :func:`_render_content` uses — the adapter takes the
#: wrapping and writes a marker onto every piece — and it is the shape rather than the
#: character that is the convention.
_CONTINUATION: Final = "↳ "


def _print(line: str, *, to: Console | None = None) -> None:
    r"""Print one line this adapter authored, marking every continuation of it (#2072).

    **Almost every line this module writes interpolates an engine-supplied value into
    text this adapter wrote** — ``  Why: {reason}``, ``    {key} = {value}``,
    ``  {index}. {intent}``, a span line, a belief field. :func:`_safe` replaces the
    value's newlines for exactly that reason (#1336): a newline would forge a second
    line indistinguishable from one this adapter wrote. But the renderer inserts breaks
    of its own that no neutralisation of the value can reach — Rich wraps at the
    console width and **does not repeat a literal prefix on the continuations**, so a
    long value's tail arrives at the margin carrying nothing that says it is data. At
    width 40 a 500-character parameter value rendered as a dozen unmarked lines.

    **What stood between that and a forgery was an accident of indentation.** A
    continuation lands at column 0 while a card's fields carry a two- or four-space
    indent, so a forged ``  Why: …`` did not line up with the real one *at that width*
    and *while every caller kept its indent*. Neither is a property anything holds, so
    the distinction is made deliberately here instead: the wrapping is taken by this
    adapter and every display line after the first carries :data:`_CONTINUATION`.

    **The shape is the one the block renderer already uses**, and adopting it rather
    than inventing another is the whole of the shape decision: the adapter takes the
    wrapping itself, by Rich's own measurement, and writes a marker onto every piece.
    :func:`_render_content` does exactly that for a value printed as a block of its own.

    **Every line goes through this, not only the ones a value reaches.** Whether a
    composed line carries an engine-supplied value is not decidable at the call site:
    the value often arrives through a helper that returns a whole phrase
    (:func:`_egress_span_line`, :func:`_message_for`, :func:`_scope_phrase`), and a rule
    that has to be re-decided at each future call site is precisely the defence #2072
    found wanting. A line with no value in it costs a marker on a wrap that would
    otherwise be ambiguous to the eye, which is not a cost worth a second convention.

    **A line that fits is printed exactly as it was**, byte for byte, which is what
    keeps this from being a change to every rendering in the module: only a line the
    console would have broken is rendered differently, and only from its second display
    line on. :func:`_render_content` takes the same care for the same reason.

    **A ``\n`` in the composed string is this adapter's own**, since :func:`_safe` eats
    a value's — and no line here carries one between two pieces of content, only ahead
    of a block or after it. Those are reproduced as the blank lines they are. The
    exception is a line that interpolates :func:`_safe_prose`, where a break after the
    head *is* the value's, and there the following lines are continuations and are
    marked as such: the value can never put a second field under the real one.

    **Four site classes do not take this, and each has its own answer to the same
    question.** A value printed as a block of its own is marked line by line by
    :func:`_render_content`, which wraps it itself and hands this console a
    :class:`~rich.text.Text` already measured to fit — a second wrap would find nothing
    to break. A command hint goes through :func:`_print_hint`, which asks the *terminal*
    to fold rather than breaking the line at all, because a hint Rich broke pastes as
    two commands (#1023); the fold leaves no marked line, and that is the trade #1023
    made and this does not reopen. And the composed answer is printed as the block of
    prose it is: no text this adapter wrote shares a line with it, so a break in it
    forges nothing — which is the argument :func:`_safe_prose` records for keeping its
    newlines in the first place.

    **What wrapping costs is one space per break**: an unbroken run is folded and its
    pieces concatenate back to it, and a run of words breaks at a space because on a
    screen the break *is* that space. Nothing is truncated, elided or summarised here.

    Rich markup is resolved once, by the console, and what is printed on a wrapped line
    is a :class:`~rich.text.Text` — so the escaping :func:`_safe` applied cannot be
    re-parsed by the print, which is :func:`_safe_prose`'s reason held one step later.

    Args:
        line: The line, with its markup, exactly as it would have been printed.
        to: The console to write to. Defaults to :data:`console`, read at call time so
            a test that substitutes it is honoured; the export path's error boundary
            passes :data:`error_console` (ADR-0186 §9).
    """
    target = console if to is None else to
    segments = line.split("\n")
    lead = 0
    while lead < len(segments) - 1 and not segments[lead]:
        lead += 1
    trail = len(segments)
    while trail - 1 > lead and not segments[trail - 1]:
        trail -= 1
    for _ in range(lead):
        target.print()
    _print_marking_continuations(target, segments[lead:trail])
    for _ in range(len(segments) - trail):
        target.print()


def _print_marking_continuations(target: Console, segments: Sequence[str]) -> None:
    """Write one logical line, its first display line bare and the rest marked.

    Split out of :func:`_print` so that the blank lines around a line are settled in
    one place and the marking in another; see there for why the marker exists and why
    a line that fits is printed untouched.

    The gutter takes the head's own indentation, so a card's fields keep their column
    and the marker sits where the eye already is. Below the gutter's own width there is
    no rendering that both shows the text and marks it — the room is clamped to one
    column and the marked line then wraps.

    Args:
        target: The console to write to.
        segments: The line's pieces, split on the newlines the composed string carries.
            The first is the head; every later one is a continuation the value supplied.
    """
    head = segments[0]
    if len(segments) == 1 and target.render_str(head).cell_len <= target.width:
        target.print(head)
        return
    indent = head[: len(head) - len(head.lstrip(" "))]
    gutter = Text(f"{indent}{_CONTINUATION}", style="dim")
    room = max(target.width - gutter.cell_len, 1)
    for position, segment in enumerate(segments):
        body = segment[len(indent) :] if position == 0 else segment
        for offset, piece in enumerate(target.render_str(body).wrap(target, room)):
            marked = position > 0 or offset > 0
            target.print((gutter if marked else Text(indent)) + piece)


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

    ``soft_wrap`` is the answer, for this reason: Rich emits the line as it stands and the terminal
    folds it, which costs a word break mid-word and keeps the line *one* line to
    anything that copies it. It is the whole of the decision, taken once here rather
    than per site — an ``overflow`` or ``crop`` setting would instead **truncate** a
    long hint, which turns a command that pastes wrongly into one that pastes
    silently short.

    **It is for the print that carries the command, and only that one.** A hint
    embedded in a paragraph takes this too, because the fold hazard is the same
    wherever the command sits; prose with no command in it keeps Rich's wrapping,
    which reads better and has nothing to lose.

    **So a hint is the one line here that does not go through :func:`_print`**, and it
    is the same decision seen from the other side: what that function does is take the
    wrapping and mark what it broke, and what this one wants is not to break the line
    at all. A folded hint carries no marker, which is #2072's exposure kept for
    #1023's reason — a wrong command is worse than an unmarked continuation, and the
    argument is quoted (:func:`_argument`) or withheld (:func:`_uncopyable`) before it
    reaches the line.

    Args:
        line: The hint, with its markup, exactly as it would have been printed.
    """
    console.print(line, soft_wrap=True)


def _render_conversations(
    page: tuple[ConversationSummary, ...], *, limit: int, offset: int
) -> None:
    """Render one page of conversations (ADR-0074 §2).

    Ordered by last activity, which is the store's contract and not re-sorted here.
    **No total is shown**, and none is available to show: "is there more" is
    answered by asking for the next page, exactly as the belief listing answers it.
    """
    if not page:
        _print("[dim]No conversations yet — 'assistant chat' starts one.[/]")
        return
    _print(f"[bold]{len(page)} conversation(s)[/], most recently active first.")
    for conversation in page:
        _print(f"\n  [bold cyan]{_safe(conversation.id)}[/]")
        _print(f"  [dim]Started:[/] {_when(conversation.started_at)}")
        _print(f"  [dim]Last active:[/] {_when(conversation.last_active_at)}")
        if conversation.last_turn_at is None:
            _print("  [dim]No turn has been recorded in it yet.[/]")
        else:
            _print(f"  [dim]Last recorded turn:[/] {_when(conversation.last_turn_at)}")
    if limit and len(page) == limit:
        _print(f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]")


def _render_forget_conversation_prompt(digest: ConversationDigest) -> None:
    """Show what forgetting a conversation will forget (ADR-0074 §8, ADR-0293 §5:7).

    **The count and span, not every turn.** A transcript at a prompt is not
    something a person can judge, and showing nothing would be taking consent for
    something unseen. The count is of turns *recorded*: one whose episode has since
    expired or been deleted still happened, and saying otherwise would understate
    what is being destroyed.
    """
    _print("\n[bold yellow]About to forget this conversation[/]")
    _print(f"  [bold cyan]{_safe(digest.id)}[/]")
    _print(f"  [dim]Started:[/] {_when(digest.started_at)}")
    if digest.last_turn_at is None:
        _print("  [dim]Turns recorded:[/] none")
    else:
        _print(
            f"  [dim]Turns recorded:[/] {digest.recorded_turns}, "
            f"the last at {_when(digest.last_turn_at)}"
        )
    _print(
        "\n  [yellow]Forgetting removes its episodes from the assistant's memory, so it "
        "no longer recalls them anywhere else. The conversation and its transcript stay: "
        "the assistant still reads it while you keep talking there, and only deleting "
        "removes it.[/]"
    )
    _print(
        "  [dim]Turns already deleted or past their retention window stay gone; "
        "nothing is restored.[/]"
    )


def _render_forget_unseen_conversation_prompt(conversation_id: str) -> None:
    """Show what forgetting a conversation no longer shown will do (ADR-0293 §2:5).

    There is no count or span to show: the conversation is deleted, or never was.
    What is said is what forgetting would reach, so consent is still taken for
    something stated.
    """
    _print(
        f"\n[yellow]No conversation has the id[/] {_safe(conversation_id)} [yellow]any "
        "more — it may have been deleted, or never existed.[/]"
    )
    _print(
        "  [yellow]Forgetting it still removes any episodes the assistant holds from it, "
        "so it no longer recalls them anywhere else.[/]"
    )


def _render_no_such_conversation(conversation_id: str) -> None:
    """Report an id that names no conversation this surface can show (ADR-0074 §1, §8).

    Unknown, already deleted, or reclaimed after its retention horizon passed — all
    three look the same from here on purpose, because a surface that distinguished
    them would report on conversations it is meant to have forgotten.
    """
    _print(
        f"[yellow]No conversation has the id[/] {_safe(conversation_id)}. "
        "It may never have existed, or you may have deleted it already — "
        "'assistant conversations' lists the ones that are still here."
    )


def _confirm_forget_conversation(_digest: ConversationDigest | None) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    The conversation-scoped sibling of :func:`_confirm_forget` (I/O; ADR-0042 §6).
    Defaults to **no**, for its reason: the question is about destroying something
    irreversibly, and more of it.
    """
    return typer.confirm("Forget it?", default=False)


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


#: A memory's standing in plain words, as this surface says it (ADR-0328 §6:1, §15:4).
_STANDING_WORDS: Final[dict[MemoryStanding, str]] = {
    MemoryStanding.CONFIRMED: "you confirmed this wording",
    MemoryStanding.SAID: "you said it",
    MemoryStanding.SOURCE: "from a source",
    MemoryStanding.INFERENCE: "my inference",
}

#: Where a support came from, in plain words (ADR-0328 §4's origin table).
_ORIGIN_WORDS: Final[dict[SupportOrigin, str]] = {
    SupportOrigin.USER_MESSAGE: "your message",
    SupportOrigin.OUTSIDE_INPUT: "a report from outside",
    SupportOrigin.CONFIRMATION: "your yes to my question",
    SupportOrigin.EVIDENCE: "outside content I read",
    SupportOrigin.ASSISTANT_MESSAGE: "my own message",
    SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE: "my own message, over outside content",
    SupportOrigin.REMEMBERED: "something I chose to remember",
    SupportOrigin.REMEMBERED_OVER_OUTSIDE: "something I chose to remember, over outside content",
    SupportOrigin.LEGACY: "a record kept before memories had supports",
    SupportOrigin.LEGACY_OUTSIDE: (
        "a record kept before memories had supports, resting on outside content"
    ),
    SupportOrigin.OBSERVER_INFERENCE: "my inference from the other supports",
    SupportOrigin.PINNED: "your pin",
}


def _standing_line(belief: Belief | BeliefSummary) -> str:
    """The row's head: its standing in plain words, its band, and its status (§15:4).

    The band leads as it always has (ADR-0073 §4: never omitted, never implied by
    position alone), and the standing beside it says which of the band's standings it
    is. A memory that ended or was marked wrong is never listed (the listing is live),
    but the single view says so if one ever reaches it.
    """
    if belief.standing is None:
        return f"\n  [bold cyan]{belief.band.value}[/] · a captured exchange"
    # ADR-0345 §12:4: a memory marked as the assistant's statement is said to be what I
    # said, never by its standing as a source's word or yours.
    standing = (
        _SAID_BY_ME
        if MemoryMark.ASSISTANT_STATEMENT in belief.marks
        else _STANDING_WORDS[belief.standing]
    )
    head = f"\n  [bold cyan]{belief.band.value}[/] · {standing}"
    match belief.status:
        case MemoryStatus.CURRENT:
            return head
        case MemoryStatus.ENDED:
            return f"{head} · [yellow]no longer holds[/]"
        case MemoryStatus.WRONG:
            return f"{head} · [yellow]marked wrong[/]"
        case None:  # pragma: no cover - a memory always carries one
            return head
        case _:  # pragma: no cover - exhaustive
            assert_never(belief.status)


def _evidence_words(belief: Belief | BeliefSummary) -> str:
    """The evidence summary, said where the standing is inference (ADR-0328 §15:4)."""
    evidence = belief.evidence
    against = f", {evidence.against} against it" if evidence.against else ""
    # A legacy support points at no exchange (ADR-0328 §16:4), so a count of none is
    # left unsaid rather than rendered as "across 0 exchange(s)".
    across = f" across {evidence.episodes} exchange(s)" if evidence.episodes else ""
    # §7:2's latest `when`, which can be a newer piece against it than As of shows.
    latest = (
        " None of it is dated."
        if evidence.latest is None
        else f" The latest piece is from {_when(evidence.latest)}."
    )
    return (
        f"I worked it out from {evidence.supporting} piece(s) of support{across}{against}.{latest}"
    )


def _outside_warrant(belief: Belief | BeliefSummary) -> str:
    """That some of its warrant came from outside, or nothing (ADR-0189 §4, ADR-0328 §12).

    Read off ``rests_on_outside_content`` as the engine computed it, never recomputed
    here. Silent on ``False`` rather than negative: a ``False`` is *nothing outside is
    recorded in this warrant*, never *nothing outside influenced it* (ADR-0328 §7:7). It
    says nothing about the memory's own wording, which is this system's sentence
    (ADR-0098 §1).
    """
    if not belief.rests_on_outside_content:
        return ""
    return (
        " Some of what it rests on came from outside rather than from you — the wording "
        "is still my own sentence, but its warrant is not entirely mine."
    )


#: ADR-0345 §12:4: the standing words a memory marked ``assistant_statement`` takes.
_SAID_BY_ME: Final = "what I said"


def _holder_words(holder: SupportHolder) -> str:
    """Whose belief a support records, as this surface says it (ADR-0345 §12)."""
    match holder.kind:
        case HolderKind.PERSON if holder.identifier == OWNER_PERSON_ID:
            return "you"
        case HolderKind.PERSON:
            return f"another person ({_safe(holder.identifier or '')})"
        case HolderKind.OUTSIDE_SOURCE if holder.claimed:
            return f"a forward claimed to come from {_safe(holder.identifier or '')}"
        case HolderKind.OUTSIDE_SOURCE:
            return f"the source {_safe(holder.identifier or '')}"
        case HolderKind.ASSISTANT_STATEMENT:
            return "my own words"
        case _:
            return "an unknown source"


def _said_why(belief: Belief | BeliefSummary) -> str:
    """Why a memory marked ``assistant_statement`` is held (ADR-0345 §12:4).

    What I said, where and when, and who kept it where someone did: never as your word
    or a source's, whatever its standing.
    """
    when = ", ".join(_when_or_unknown(one.when) for one in belief.statements) or "unknown"
    kept = [one for one in belief.holders if one.kind is HolderKind.PERSON]
    keepers = ", ".join(_holder_words(one) for one in kept)
    keeper = f" {keepers[:1].upper()}{keepers[1:]} kept it." if kept else " Nobody but me said it."
    return f"I said this, in my message of {when}; it is a record of what I said.{keeper}"


def _why(belief: Belief | BeliefSummary) -> str:
    """Why this memory is held: its standing, said in plain words (ADR-0328 §15:4).

    Total over :class:`~ai_assistant.core.types.MemoryStanding`, mechanically so: the
    wildcard does nothing but ``assert_never``. An inference says its evidence summary,
    and whether any of it came from outside (ADR-0189 §4's clause, on the ``DERIVED``
    band where that ADR put it). A memory marked ``assistant_statement`` is said to be
    what I said, whatever its standing (ADR-0345 §12:4).
    """
    if MemoryMark.ASSISTANT_STATEMENT in belief.marks:
        return _said_why(belief)
    match belief.standing:
        case None:
            return _why_episodic(belief)
        case MemoryStanding.CONFIRMED:
            return _confirmed_why(belief)
        case MemoryStanding.SAID:
            return "you told me, and your own word is the whole of it."
        case MemoryStanding.SOURCE:
            # Every origin ranked at source (ADR-0328 §4): an outside report, an
            # evidence item read from outside content, or a message of my own. What it
            # rests on says which; nothing here claims an integration reported it.
            return (
                "it came from a source rather than from you — neither your word nor my "
                "inference. What it rests on says which source."
            )
        case MemoryStanding.INFERENCE:
            return _evidence_words(belief) + _outside_warrant(belief)
        case _:  # pragma: no cover - exhaustive
            assert_never(belief.standing)


def _confirmed_why(belief: Belief | BeliefSummary) -> str:
    """How the person confirmed a memory's wording: by a yes, by a pin, or both (#3333).

    A ``confirmation`` support is a yes to a question (ADR-0328 §6:1), and a ``pinned``
    one is a pin the person made (ADR-0338 §4:3-§4:4); both rank at "you confirmed this
    wording". Read off the counted supports backing it, where the single view carries
    them. A listing's summary carries none, and there the sentence names neither, rather
    than one that may not be how it was confirmed. The page says the same
    (``confirmedHow``).
    """
    if not isinstance(belief, Belief):
        return "you confirmed this wording."
    backing = [
        one for one in belief.supports if one.counts and one.direction is SupportDirection.FOR
    ]
    asked = any(one.origin is SupportOrigin.CONFIRMATION for one in backing)
    pinned = any(one.origin is SupportOrigin.PINNED for one in backing)
    if asked and pinned:
        return "you confirmed this wording when I asked you, and by pinning it."
    if pinned:
        return "you confirmed this wording by pinning it."
    if asked:
        return "you confirmed this wording when I asked you."
    return "you confirmed this wording."


def _why_episodic(belief: Belief | BeliefSummary) -> str:
    """Why a captured episode is held: because it happened (ADR-0075 §2, ADR-0223 §5).

    Listed only where ``--kind episodic`` asked for it (ADR-0074 §6). Its outside mark
    is said in the episode's own words: the material in front of this system traced
    back to a connected source, and the record is still its own account.
    """
    outside = (
        " Some of the material I had in front of me during this exchange traces back to a "
        "connected source rather than to you — the record above is still my own account of "
        "what was said."
        if belief.rests_on_outside_content
        else ""
    )
    return (
        "this records an exchange that happened — I captured it at the time, so there was "
        "nothing to work out and nothing to weigh."
    ) + outside


def _forget_warning(band: BeliefBand) -> str:
    """What forgetting a memory in this band costs (ADR-0073 §5).

    The ceremony is uniform in mechanism and asymmetric in message, because the
    consequence is: an assertion is not re-derivable and losing one is unrecoverable
    (ADR-0072 §1, ADR-0038 §2), while a derived or attested memory loses the memory
    and not its origin. Total over the bands, like :func:`_why`.
    """
    match band:
        case BeliefBand.ASSERTED:
            return "You told me this. Forgetting it is permanent — nothing can work it out again."
        case BeliefBand.DERIVED:
            return (
                "I worked this out. Forgetting it destroys the memory but not what I "
                "worked it out from, so I may reach it again."
            )
        case BeliefBand.ATTESTED:
            return (
                "This came from a source, not from you. Forgetting it destroys my copy but "
                "not the source, so I may come across it again."
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
        _print(f"  {lines[0]}")
        return
    gutter = Text("  │ ", style="dim")
    room = max(console.width - len(gutter), 1)
    for text_line in lines:
        for wrapped in Text.from_markup(text_line).wrap(console, room):
            console.print(gutter + wrapped)


def _render_belief_summary(summary: BeliefSummary) -> None:
    """Render one row of the **listing** (ADR-0328 §15:1, ADR-0085 §4a).

    A :class:`~ai_assistant.core.types.BeliefSummary` carries no support, so this
    renderer could not print one if it tried; the supports belong to the single view.
    """
    _render_belief_fields(summary)


def _render_belief(belief: Belief) -> None:
    """Render the **single-memory** view: the same fields, plus every support (§15:2)."""
    _render_belief_fields(belief)
    _render_supports(belief)


def _render_reported_by(belief: Belief | BeliefSummary) -> None:
    """What reported it and when that source said so, on its own clock (ADR-0189 §1, §4).

    An episode's provenance attestation, or the source details a memory's standing rests
    on (ADR-0328 §2:6's latest backing source support); nothing where there are none.
    """
    if belief.attestation is None:
        return
    _print(
        f"  [dim]Reported by:[/] {_safe(belief.attestation.reported_by)}, as of "
        f"{_when(belief.attestation.reported_at)} on its own clock"
    )


def _render_belief_fields(belief: Belief | BeliefSummary) -> None:
    """Render what ADR-0328 §15:4 requires a surface showing a memory to show.

    At least: its standing in plain words, its age, its evidence summary where its
    standing is inference, its reading certainty where that is not ``sure``, every
    let-down, and the legacy mark. Beside them, as before: the band, the wording,
    the end of its validity window where one is set, and the id ``forget`` takes. Its
    age is when it was learned and as of when it was last confirmed, each said as
    unknown where nothing dates it, which is neither fresh nor stale (§7:3).

    **No confidence is shown**, and none is carried (§15:3).

    Engine-supplied text — the wording, the id, a source's name — is neutralised for
    this terminal like any other (``_safe``, ADR-0042 §4). The band, the standing and
    the status are this system's own closed vocabularies, not carried data.
    """
    _print(_standing_line(belief))
    _render_content(belief.content)
    _print(f"  [dim]Why:[/] {_why(belief)}")
    if belief.kind == "episodic":
        # An episode has no standing, supports or reading (ADR-0074 §6): when it
        # happened, its window and its id are what it carries.
        _print(f"  [dim]Happened:[/] {_when_or_unknown(belief.learned)}")
        _render_reported_by(belief)
        if belief.valid_until is not None:
            _print(f"  [dim]Kept until:[/] {_when(belief.valid_until)}")
        _print(f"  [dim]id:[/] {_safe(belief.id)}")
        return
    _print(f"  [dim]Learned:[/] {_when_or_unknown(belief.learned)}")
    _print(f"  [dim]As of:[/] {_when_or_unknown(belief.as_of)}")
    if belief.holders and belief.holders != (SupportHolder.person(OWNER_PERSON_ID),):
        # ADR-0345 §12:1: whose belief it is, wherever that is not yours alone.
        _print(f"  [dim]Held by:[/] {', '.join(_holder_words(one) for one in belief.holders)}")
    _render_reported_by(belief)
    certainty = belief.reading_certainty
    if certainty is not ReadingCertainty.SURE:
        reading = "not judged" if certainty is None else certainty.value
        _print(f"  [dim]How sure the reading was:[/] {reading}")
    track = belief.track_record
    if track.let_down:
        _print(
            f"  [yellow]Let you down {track.let_down} time(s)[/] of the "
            f"{track.relied_on} I relied on it."
        )
    if belief.legacy:
        _print(
            "  [dim]Legacy:[/] kept before memories had supports; what it rested on then "
            "is shown as it was recorded."
        )
    if belief.unbacked:
        _print("  [yellow]Nothing that counts backs this wording now.[/]")
    if belief.supports_gone:
        _print(
            "  [yellow]Everything it rested on is gone.[/] I still hold it — I have "
            "not unlearnt it because the evidence went."
        )
    if belief.valid_until is not None:
        _print(f"  [dim]Believed until:[/] {_when(belief.valid_until)}")
    _print(f"  [dim]id:[/] {_safe(belief.id)}")


def _when_or_unknown(instant: datetime | None) -> str:
    """:func:`_when`, or that nothing dates it (ADR-0328 §7:3-§7:4)."""
    return "unknown" if instant is None else _when(instant)


def _render_supports(belief: Belief) -> None:
    """Render each support behind one memory, a gone one as gone (ADR-0328 §15:2, §15:7).

    A support whose part no longer resolves is **an explicit tombstone** — never a
    bare id, never a silent gap, and never shown as evidence (ADR-0073 §4's floor). It
    still counts, which is why it is listed. One that was stopped from counting says so.
    An episode rests on none, and prints nothing here.
    """
    if not belief.supports:
        return
    _print("  [dim]Rests on:[/]")
    for support in belief.supports:
        against = (
            " · [yellow]against it[/]" if support.direction is SupportDirection.AGAINST else ""
        )
        stopped = " · [dim]no longer counted[/]" if not support.counts else ""
        when = "" if support.when is None else f" · {_when(support.when)}"
        source = support.source_details
        # ADR-0189 §4: the source's own reporting instant, said as its clock, beside the
        # `when` this system read the part at.
        named = (
            ""
            if source is None
            else f" · {_safe(source.reported_by)}, which said so as of "
            f"{_when(source.reported_at)} on its own clock"
        )
        _print(f"    - {_ORIGIN_WORDS[support.origin]}{named}{when}{against}{stopped}")
        if support.content is None:
            _print("      [yellow]—[/] [dim]what it pointed at is gone.[/]")
        else:
            _print(f"      {_safe(support.content)}")
        if support.note:
            _print(f"      [dim]{_safe(support.note)}[/]")


def _render_beliefs(page: tuple[BeliefSummary, ...], *, limit: int, offset: int) -> None:
    """Render one page of memories (ADR-0073 §7).

    **No total is shown**, and none is available to show: "is there more" is answered
    by asking for the next page, so a full page says so and names the offset that
    would fetch it, rather than implying a count nobody computed.
    """
    if not page:
        _print("[dim]No live belief matches.[/]")
        return
    _print(f"[bold]{len(page)} belief(s)[/], most recently revised first.")
    for summary in page:
        _render_belief_summary(summary)
    if limit and len(page) == limit:
        _print(f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]")


def _render_forget_prompt(belief: Belief) -> None:
    """Show what is about to be destroyed, and what destroying it costs (ADR-0073 §5).

    Three things, in this order, because a person cannot consent to destroying
    something they were not shown (ADR-0042 §4, ADR-0052 §4):

    1. the memory itself, in full;
    2. the band-appropriate warning — what is lost, and what is not;
    3. what the confirmation actually covers. It is consent to forget **the memory
       that id names**, not a guarantee that what is destroyed is byte-for-byte what
       was just rendered: the show and the delete are two calls and the window
       between them is named rather than closed (ADR-0073 §5). And it destroys rather
       than retires (ADR-0073 §6).
    """
    _print("\n[bold yellow]About to forget this belief[/]")
    _render_belief(belief)
    _print(f"\n  [yellow]{_forget_warning(belief.band)}[/]")
    _print(
        "  This destroys the record: nothing of it is kept, not even in an export. "
        "To fix it instead, correct me in [bold]assistant chat[/] by replying to what "
        "I got wrong."
    )
    _print(
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
    _print(
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
        _print(
            "[yellow]No sources are available to connect.[/] Nothing is configured "
            "for this installation to read. Configuration says *where* a source is; "
            "a grant says *whether* I may read it — and neither stands in for the "
            "other, so there is nothing to grant until one is configured."
        )
        return
    _print(f"[bold]{len(offered)}[/] source(s) you can connect me to:\n")
    for one in offered:
        _print(f"  [bold cyan]{_safe(one.source)}[/]")
        # The location is shown and comes to rest nowhere: it is on this response
        # and on no stored record, in no log and in no export (ADR-0097 §9a).
        where = "not configured" if one.location is None else _safe(one.location)
        _print(f"    reads from: {where}")
        if one.live is None:
            _print("    [dim]not granted — I read nothing from it[/]")
        else:
            _print(
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
    _print(
        f"[yellow]I cannot offer a source called[/] {_safe(source)}[yellow].[/] "
        "You can only grant a source I can show you first, which is what keeps a "
        "typo from becoming a permission."
    )
    if offered:
        names = ", ".join(_safe(one.source) for one in offered)
        _print(f"Available: {names}. See 'assistant sources' for the details.")
    else:
        _print("Nothing is configured for me to read, so there is nothing to grant.")


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
    _print(f"About to connect [bold cyan]{_safe(chosen.source)}[/].\n")
    if chosen.location is None:
        _print("  [yellow]It has no configured location.[/]")
    else:
        _print(f"  It reads from: [bold]{_safe(chosen.location)}[/]")
    _print(f"  You would be allowing: {_scope_phrase(scope)}.")
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
    _print(
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
        _print("[yellow]Nothing recorded.[/] You have not granted or withdrawn anything.")
        return
    _print(f"[bold]{len(recorded)}[/] record(s), most recent decision first:\n")
    for record in recorded:
        act = "withdrew" if record.revokes is not None else "granted"
        _print(
            f"  [bold]{_when(record.decided_at)}[/] — {act} "
            f"[bold cyan]{_safe(record.source)}[/] for {_scope_phrase(record.scope)}"
        )
        _print(f"    [dim]{_safe(record.id)}[/]")
    if len(recorded) == limit:
        _print(f"\n[dim]Showing {limit}. Ask for more with --limit; there is no total count.[/]")
    _print(
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
        _print(
            "[yellow]You have not granted anything.[/] I am allowed to read no "
            "source at all. 'assistant sources' lists what you could connect me to."
        )
        return
    _print(f"[bold]{len(standing)}[/] source(s) you currently allow me to read:\n")
    for record in standing:
        _print(f"  [bold cyan]{_safe(record.source)}[/]")
        _print(f"    [green]allowed for[/] {_scope_phrase(record.scope)}")
        _print(f"    [dim]granted {_when(record.decided_at)}[/]")
        withdrawal = (
            f"assistant revoke {_argument(record.source)}"
            if _is_pasteable(record.source)
            else "assistant revoke"
        )
        _print_hint(f"    [dim]withdraw with '{withdrawal}'[/]")
        console.print()
    _print(
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
    _print(
        f"[yellow]I cannot amend the grant on[/] {_safe(source)}[yellow].[/] "
        "Amending makes a new grant, and I only grant a source I can show you "
        "first — this one is not among the sources I can offer."
    )
    if offered:
        names = ", ".join(_safe(one.source) for one in offered)
        _print(f"Available to grant: {names}. See 'assistant sources'.")
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
    _print(f"About to change the grant on [bold cyan]{_safe(chosen.source)}[/].\n")
    if chosen.location is None:
        _print("  [yellow]It has no configured location.[/]")
    else:
        _print(f"  It reads from: [bold]{_safe(chosen.location)}[/]")
    if chosen.live is None:
        _print(
            "  [yellow]It is not granted right now.[/] I will still withdraw first, "
            "then grant — that is the only shape this act has."
        )
    else:
        _print(f"  It is currently allowed for: {_scope_phrase(chosen.live.scope)}")
    _print(f"  It would then be allowed for: {_scope_phrase(scope)}")
    _print(
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
            _print(f"[green]The {act} landed.[/]{found}")
        case _ActOutcome.NOT_LANDED:
            _print(
                f"[red]The {act} is known not to have landed[/] — I was refused, so "
                f"nothing was written: {_safe('; '.join(detail))}"
            )
        case _ActOutcome.UNKNOWN:
            because = f" {_safe('; '.join(detail))}" if detail else ""
            _print(
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
        _print(
            "[yellow]I sent no new grant.[/] I could not tell whether the withdrawal "
            "happened, and sending a second act to find out would only give me an "
            "answer I could not read. The amendment is incomplete."
        )
        return
    _print("[yellow]I sent no new grant.[/] The amendment is incomplete.")


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
    _print(
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
        _print(
            f"[dim]I could not read what {_safe(source)} is allowed for, so I am not "
            "saying. Try 'assistant granted'.[/]"
        )
        return
    if state is None:
        _print(f"I read [bold]{_safe(source)}[/]'s state: nothing is granted on it.")
        return
    _print(f"I read [bold]{_safe(source)}[/]'s state: it is allowed {_scope_phrase(state.scope)}.")


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
            _print(
                "[dim]No notifications on this page.[/] That says nothing about what "
                "is held — ask from the first page ('--offset 0' with a limit above 0) "
                "to see."
            )
            return
        _print(
            "[dim]I am holding nothing for you.[/] Out of the box nothing reaches you "
            "unprompted — see 'assistant tune --help' for the three separate acts that "
            "arm it, and 'assistant notification-settings' for what is set now."
        )
        return
    _print(f"[bold]{len(page)} notification(s)[/] I am holding, oldest first.")
    for record in page:
        _render_notification(record, now=now)
    if limit and len(page) == limit:
        _print(f"\n[dim]That is a full page; there may be more — try --offset {offset + limit}.[/]")


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
    clock reading and nothing more.

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
    _print(f"\n  [bold cyan]{_safe(record.id)}[/]")
    _print(f"  [bold]{_safe(candidate.summary)}[/]")
    if candidate.detail is not None:
        _print(f"  {_safe(candidate.detail)}")
    _print(
        f"  [dim]Class:[/] {_safe(candidate.notification_class)} "
        f"[dim](noticed by {_safe(candidate.producer)})[/]"
    )
    _render_notification_ruling(record)
    _print(f"  [dim]Noticed:[/] {_when(candidate.noticed_at)}")
    if candidate.expires_at is None:
        _print("  [dim]Expires:[/] never — which is why it is held rather than urgent")
    elif _has_perished(candidate, now):
        _print(
            f"  [yellow]Expired:[/] {_when(candidate.expires_at)} "
            f"[dim]— it is kept and readable, and it will not reach you[/]"
        )
    else:
        _print(f"  [dim]Expires:[/] {_when(candidate.expires_at)}")
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
            _print("  [dim]Ruled:[/] to reach you at the time")
        case NotificationDispositionKind.HOLD:
            _print("  [dim]Ruled:[/] held for when you next look")
        case NotificationDispositionKind.DROP:
            _print(f"  [dim]Ruled:[/] ruled out — {_condition_phrase(record.reason)}")
        case _:  # pragma: no cover — exhaustive over the enum
            assert_never(record.kind)
    for condition in record.failed:
        _print(f"  [dim]Not now, because:[/] {_condition_phrase(condition)}")
    if record.dismissed_at is not None:
        _print(f"  [dim]Dismissed:[/] {_when(record.dismissed_at)}")
    if record.dropped_at is not None:
        _print(f"  [dim]Ruled out:[/] {_when(record.dropped_at)}")


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
    The same exposure on the older ``revoke`` hints is #984 rather than a wider diff
    here.

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
        _print(
            "  "
            + _uncopyable(
                "Its id or its class",
                "The 'dismiss' and 'tune' commands still take them, given the exact bytes.",
            )
        )
        return
    _print_hint(f"  [dim]Deal with it:[/] assistant dismiss {_argument(record.id)}")
    if NotificationCondition.PERISHABLE in record.failed:
        _print(
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
    _print("[bold]How far each class may reach you[/]")
    for row in preferences.reaches:
        _print(
            f"  {_safe(row.notification_class)}: [bold]{row.reach.value}[/] "
            f"[dim]— {_reach_phrase(row.reach)}[/]"
        )
    _print(
        f"  [dim]every other class:[/] [bold]{DEFAULT_NOTIFICATION_REACH.value}[/] "
        f"[dim]— {_reach_phrase(DEFAULT_NOTIFICATION_REACH)} (the shipped default)[/]"
    )
    _print("\n[bold]Quiet hours[/] [dim](read in your configured timezone)[/]")
    if not preferences.quiet_windows:
        _print("  [dim]none — no part of the day is quiet[/]")
    for window in preferences.quiet_windows:
        _print(f"  {window.start_time:%H:%M}-{window.end_time:%H:%M}")
    _print("\n[bold]Interruption budget[/]")
    _print(
        f"  {preferences.interruption_budget} per {_hours(preferences.budget_window)}"
        f"{' [dim]— never interrupt[/]' if preferences.interruption_budget == 0 else ''}"
    )
    _print("\n[dim]Change any of these with 'assistant tune'.[/]")


def _confirm_forget(_belief: Belief) -> bool:
    """Read the human's yes/no *without* rendering — the caller already displayed it.

    The question on the deletion path (I/O; ADR-0042 §6). Defaults to **no**: the
    question is about destroying something irreversibly, so a bare Enter must not be the
    answer that destroys it.
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


def _recipient_line(protocol: DestinationProtocol | None, canonical: str | None) -> str:
    """The selected-recipient arm of a canonical destination set member.

    The recorded binding's, rendered under **ADR-0178 §7's** obligations because
    ADR-0186 §7 renders a history row's recipients under them rather than a second
    set of its own: "a second, differently worded floor would be a second vocabulary
    to keep in step with the first, and the failure would be a history that renders
    a disclosure the card showed, or shows one it did not". The confirmation card
    this function was shared with retired with the old path (ADR-0309 §5). The
    account is the caller's and the recipient is this function's.

    Args:
        protocol: The member's protocol, as the value carries it.
        canonical: The member's canonical form, as `core` derived it.

    Returns:
        The line for one selected recipient, neutralised for this terminal.
    """
    named = "" if protocol is None else protocol.value
    return f"{_safe(canonical or '')} [dim]({_safe(named)})[/]"


def _span_where(span: EgressSpan) -> str:
    """The span's key, ADR-0150 §4's pair in one spelling.

    A span is identified by ``(argument, index)``, and :func:`_egress_span_line`,
    which states what the description says about it, names it by this spelling.

    The argument is neutralised because a caller, or a model composing the call,
    can put content of its own choosing into a *key* (ADR-0150 §13). The index is
    an ``int`` the type validated and needs none.

    Args:
        span: The occurrence being named.

    Returns:
        ``argument`` where the span carries no index, ``argument[index]`` where it
        does, neutralised for this terminal.
    """
    if span.index is None:
        return _safe(span.argument)
    return f"{_safe(span.argument)}[{span.index}]"


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
    where = _span_where(span)
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


def _origin_line(*, planned_with_external_content: bool) -> str:
    """The two **recorded** origin states, in words (ADR-0181 §6).

    The two sentences a history row states (ADR-0186 §7): the third state is
    :func:`_recorded_origin_line`'s, and it is distinct from these because the
    *fact* is distinct. Neither arm names a source, the ``False`` arm is a
    self-contained sentence and not an assurance, and neither is a detection.

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


# --- rendering the audit trail (ADR-0186 §7, §8) ----------------------------
# A history row is not a question, and that difference is the whole of this
# block. ADR-0178 §7's content obligations are **borrowed** rather than restated,
# so the same helpers render the same facts here as the confirmation card did; what
# is added is the two things a record needs that a question does not — a third
# origin state (ADR-0184 §2), and a bar on presenting a ruling as an event.


def _decision_headline(outcome: PermissionOutcome, *, names_a_yes: bool) -> str:
    """What the ruling said, in one word and what the row lets it claim (ADR-0186 §7, §8).

    **Past tense, and about the ruling rather than about the call.** §8's third
    clause bars presenting a decision as a transmission — the trail "bounds
    resolutions and not executions", so a resolved ``ALLOW`` says a call was
    permitted and says nothing about whether, or how many times, it ran. "Sent"
    beside an ``ALLOW`` is the specific regression this wording exists against, and
    it is the one a status column reaches for first.

    **A ``CONFIRM`` says the call needed your yes, and claims a question only as far
    as the row can** (#3073). Since ADR-0321 a question is a message a planning round
    writes (§2), and a ``CONFIRM`` is the ruling that sends a call back to planning as
    needing you. Two kinds of ``CONFIRM`` were never put to you as a question: a call
    no round's message asked about, which is dropped (§2:2), and route (a)'s confirm,
    ruled fresh in your yes's own activation and resolved there (§4:7). The first is
    not told apart from an asked one on the row — the round records what it asked
    (§2:8), and this surface is handed decisions alone — so the line says what is
    true of both, and says that the row does not record which. The second names the
    approval it was ruled under (§4:8), so ``names_a_yes`` lets the line say so. This
    is what ADR-0321 §7:4's "becomes true" asks of the label: ADR-0186 §7's
    rendering of a ``CONFIRM`` as a question was written when the ruling *was* the
    question, and the row now says no more than that the call needed you.

    **It is never resolved by this line** (ADR-0186 §7's fifth clause). Whether it
    was answered is a *different row*, which may lie outside a bounded page, so
    nothing here renders one as denied, as allowed, as expired or as awaiting
    anything — the past tense is that bar, read on the new wording.

    Total over the enum through :func:`~typing.assert_never`, so a fourth outcome
    would fail the type check rather than render as an empty headline.

    Args:
        outcome: What the policy ruled.
        names_a_yes: Whether the row names the approval a yes made (ADR-0321 §4:8).
    """
    match outcome:
        case PermissionOutcome.ALLOW:
            return "[green]allowed[/]"
        case PermissionOutcome.DENY:
            return "[red]refused[/]"
        case PermissionOutcome.CONFIRM:
            if names_a_yes:
                return (
                    "[yellow]needed your yes[/] [dim](ruled again after your yes, "
                    "which this row names below)[/]"
                )
            return (
                "[yellow]needed your yes[/] [dim](a question to you only where a message "
                "in your conversations asked about this call, and this row does not "
                "record whether one did)[/]"
            )
    assert_never(outcome)


def _approval_giver(giver: ApprovalGiver) -> str:
    """Who gave an approval, as §4:6's *who* reads (ADR-0321 §4:6, §4:8).

    Total over the closed enum through :func:`~typing.assert_never`: a later kind of
    approval adds a member (§4:6), and this fails the type check rather than render
    a member it has no words for.
    """
    match giver:
        case ApprovalGiver.USER_THROUGH_HUB_CHAT:
            return "by you, through the hub chat"
        case ApprovalGiver.USER_THROUGH_TELEGRAM:
            return "by you, through Telegram"
    assert_never(giver)


def _approval_end(end: ApprovalEnd) -> str:
    """When an approval stops covering anything, as §4:6's *ends* reads (ADR-0321 §4:6).

    Total over the closed enum, for :func:`_approval_giver`'s reason.
    """
    match end:
        case ApprovalEnd.WHEN_USED:
            return "it ends when used: each part covers its call once"
    assert_never(end)


def _render_approval(approval: Approval, part: QuestionPart) -> None:
    """The approval a row names, in ADR-0321 §4:8's own terms (#3073).

    §4:8: "Every decision about a call that runs under an approval names the
    approval, as 'allowed by your yes at 2:15 to the question in that message,
    part 1' does". The record carries all five of §4:6's slots and the part this call
    is; this renders each of them — **who** gave it, **how** (a yes to a question,
    named by the round whose message asked it and the activation that asked),
    **given** (when, and in which activation), the part this call is, what it
    **covers**, and when it **ends** — so the trail is the user's way to read their
    own yes back, as the export already is.

    **It says what the row records and nothing more.** Like every line on this
    surface it claims no execution (ADR-0186 §8's third clause) and no liveness
    (§8's first): that the approval was spent, or still covers anything, is the
    effect records' fact and not this row's. The round and activation ids are
    rendered because a round names its message (ADR-0307 §3:1) and no other name
    for it reaches this surface; nothing here resolves one.

    Every value is neutralised for this terminal (ADR-0186 §7's last clause).

    Args:
        approval: The approval the row names.
        part: The part of the approval's question this call is (``approved_part``).
    """
    given = approval.given
    how = approval.how
    covers = ", ".join(str(one.part) for one in approval.covers)
    _print(
        f"  [bold]Your yes:[/] given {_decided_at(given.at)} "
        f"{_approval_giver(approval.who)}, in activation {_safe(given.activation_id)} "
        f"[dim](a yes to a question)[/]"
    )
    _print(
        f"    to the question in the message of round {_safe(how.round)}, asked in "
        f"activation {_safe(how.activation_id)}; this call is part {part.part}"
    )
    _print(f"    It covers part(s) {covers} of that question, and {_approval_end(approval.ends)}")


def _recorded_origin_line(
    binding: EgressBinding | CoverageUnrecordedBinding | OriginUnrecordedBinding,
) -> str:
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
    # A `CoverageUnrecordedBinding` reaches the second branch and is *right* to:
    # such a row records the origin of the call (ADR-0233 §14 puts
    # ``planned_with_external_content`` on the rung it shares with
    # :class:`~ai_assistant.core.types.EgressBinding`), so the sentence this line
    # states about it is the one the record actually supports. What such a row does
    # not record is its **coverage**, which is a different axis and which no clause
    # of ADR-0186 §7 or ADR-0233 §8 obliges a history row to state — §8's floor is
    # stated over a surface rendering a ``Confirmation``, and this renders a
    # recorded decision. Widening the annotation is therefore the whole of what this
    # epoch costs here.
    return _origin_line(planned_with_external_content=binding.planned_with_external_content)


def _recorded_destination_line(member: CanonicalDestination) -> str:
    """One member of a recorded binding's canonical destination set (ADR-0186 §7).

    The set a **binding** carries is read member by member. The set is read from
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


def _render_recorded_egress(
    binding: EgressBinding | CoverageUnrecordedBinding | OriginUnrecordedBinding,
) -> None:
    """ADR-0178 §7's content obligations over a recorded binding, in full (ADR-0186 §7).

    The confirmation card's facts in its order — the connected
    account's identity, the call's origin, the canonical destination set in both
    forms, and the payload description — because they *are* the same facts:
    ADR-0178 §5 built a ``ConfirmationEgress`` from the recorded decision, so a
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
    _print(f"  [bold]Account:[/] {_safe(binding.account.identity)}")
    _print(f"  [bold]Planned over:[/] {_recorded_origin_line(binding)}")
    _print("  Ruled over these recipients:")
    for member in binding.canonical_destination_set:
        _print(f"    {_recorded_destination_line(member)}")
    _print("  Payload described as:")
    if not binding.spans:
        _print("    [dim](the payload description names no span)[/]")
    for span in binding.spans:
        _print(f"    {_egress_span_line(span)}")


def _rests_on_the_configuration(decision: PermissionDecision) -> bool:
    """Whether this standing ``ALLOW`` is ADR-0247 §2's route (c), read off the row alone.

    **The discriminator is ``authorised_subject``, and the eligibility conjunct is
    ``closed_loop``, and neither does the other's job** (ADR-0247 §2). The digest says
    which route a row *claims* — "a non-resolving egress ``ALLOW`` whose ``authorised_by``
    is set is route (b) where ``authorised_subject`` is set and route (c) where it is
    not" — and ``closed_loop`` says whether the row is of the one kind ADR-0148 §3's new
    route covers. Both are members of the row, so this reads no store, no ``Settings`` and
    no clock, exactly as §2 requires of the discriminator and as ADR-0193 §11's second
    clause requires of every state this surface renders.

    **Why the conjunct is here and not only in the trail.** ADR-0193 §11 reserves a
    digest-free pointer "written before this ADR's implementation validated any", and
    ADR-0247 §2 rules that such a row "is *neither* route, and ADR-0193 §11 governs it
    entire" — "this ADR does not give it a basis it never had". ``closed_loop`` was added
    to :class:`~ai_assistant.core.types.EgressBinding` by ADR-0238, which lands after
    ADR-0193's implementation, so **no row predating that implementation can carry it
    ``True``**: the conjunct is what makes the exclusion exact rather than hopeful, and a
    surface branching on the digest alone would render a reserved row as a configuration
    authority the record never claimed.

    **The pointer equality is the trail's and is deliberately not restated here**
    (ADR-0247 §2: "the trail asserts what it can see"). ``AuditTrail.record`` admits a
    digest-free standing row only where ``authorised_by`` equals the binding's
    ``account.reference``, and it refuses every other one; this adapter is handed rows
    over the wire by a hub it does not own, and re-deriving that check here would decide
    the one case it cannot help with in the **wrong** direction — a closed-loop row whose
    pointer the binding contradicts would fall through to the state that *prints* the
    pointer, which is the value ADR-0148 §6 bars from every surface.

    **Only the two unrecorded binding arms are excluded by the type test**, and that is
    ADR-0247 §2 in terms: a binding that records no origin carries no ``closed_loop``
    either, so neither :class:`~ai_assistant.core.types.OriginUnrecordedBinding` nor
    :class:`~ai_assistant.core.types.CoverageUnrecordedBinding` can be eligible, and the
    refusals ADR-0184 §7 and ADR-0233 §14 make of them are untouched.

    Args:
        decision: The recorded ruling, whose outcome the caller has already established
            is ``ALLOW`` with ``resolves`` unset and ``authorised_by`` set.

    Returns:
        Whether this row is route (c) — the deployment's own configuration of its search
        provider — rather than the standing authorisation ADR-0193 §11's second state
        names.
    """
    binding = decision.egress_binding
    return (
        decision.ruling.authorised_subject is None
        and isinstance(binding, EgressBinding)
        and binding.closed_loop
    )


def _authorisation_line(decision: PermissionDecision) -> str:
    """What authorised an ``ALLOW`` — §11's three states, route (c) inside the second.

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

    **Derived from the row alone.** Nothing here reads a store or resolves an
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

    **§11's second condition now covers two bases, and ADR-0247 §2's discriminator is
    what tells them apart.** §11 enumerates three *states* and this function still
    renders three conditions; what changed under ADR-0247 is that a non-resolving
    ``ALLOW`` carrying an ``authorised_by`` is no longer only a pointer at a standing
    grant. Route (c) — an ``ALLOW`` on a ``WEB_SEARCH`` at the provider this deployment
    was configured with — takes the same shape and sets ``authorised_by`` to the
    binding's ``account.reference``, so rendering §11's second state over it would print
    a **connection reference**, which ADR-0148 §6 and §8's fourth clause bar from every
    surface: the reference "is recorded on the decision for an auditor and is rendered to
    nobody". :func:`_rests_on_the_configuration` is that split, made from the row alone,
    and it carries the reasoning for both of its conjuncts.

    **This adds no fourth state and takes nothing away from §11.** The three conditions
    are unchanged and each is still read off the pair; what ADR-0247 §2's last normative
    clause adds is *what a surface renders* inside the second — "the reason text says
    that this deployment's owner configured this search provider, and it names no origin,
    no host, no connection reference, no credential and no ``Settings`` field". So route
    (c) is rendered as its **basis with no identifier**, and route (b) — and the reserved
    digest-free pointer §11 contemplates in terms, which is neither route — is rendered
    exactly as it was. Every other clause of §11 binds unchanged on the new line: it
    claims no liveness, states nothing about a configuration being current, and is not an
    approval control, an assurance or a reason to suppress anything above it.

    **The stored pointer is untouched by any of this** (ADR-0247 §8(d)): the row still
    carries the reference and the binding still carries the origin, so "which
    configuration authorised this" stays answerable from the recorded decision alone, and
    ``assistant export-decisions`` writes the record as it stands. What is withheld is
    the rendering, and the artifact is where an auditor reads the bytes (ADR-0186 §9).

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
        without depending on another type's invariant. The route-(c) line interpolates
        **no value at all**, which is ADR-0247 §2's last normative clause rather than a
        saving: what it would have interpolated is the one value ADR-0148 §6 keeps from
        every surface.
    """
    authorised_by = decision.ruling.authorised_by
    approval = decision.approval
    if authorised_by is None:
        if approval is not None:
            return (
                "[bold]Authorised by:[/] the policy's own rules, resting on no decision of "
                "yours; what else needed you rests on your yes, named above"
            )
        return "[bold]Authorised by:[/] the policy's own rules, resting on no decision of yours"
    if decision.resolves is None:
        if _rests_on_the_configuration(decision):
            return (
                "[bold]Authorised by:[/] this deployment's own configuration: its owner "
                "configured this search provider [dim](the basis, and no identifier of "
                "it)[/]"
            )
        return (
            "[bold]Authorised by:[/] a standing authorisation this ruling names, "
            f"recorded as {_safe(authorised_by)} [dim](what the row names, and no more)[/]"
        )
    if authorised_by == decision.resolves:
        if approval is not None and decision.approved_part is not None:
            return (
                f"[bold]Authorised by:[/] your yes, named above, to part "
                f"{decision.approved_part.part} of that question [dim](it resolved this "
                f"call's ruling recorded as {_safe(authorised_by)})[/]"
            )
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
    last), and ADR-0184 §8's bar on a confirmation shape for an unrecorded origin
    binds here as it binds everywhere.

    **The digest is a digest.** It is never labelled as, rendered as or expanded
    into the payload (§8's fourth clause) — what it does is bind the arguments the
    ruling was taken over, which is exactly what the record holds and exactly what
    the line says.

    **A ``None`` binding asserts nothing** (§7's fourth clause). No recipient, no
    account and no origin is rendered, and none is denied: ``None`` means the
    request was not an egress call (ADR-0150 §1) and continues to mean exactly that.

    **A row naming an approval renders it whole** (ADR-0321 §4:8, #3073) — who gave
    the yes, how, when, the part this call is, what the approval covers and when it
    ends — through :func:`_render_approval`, after the resolution and before the
    authorisation that points at it. Such a row is an ``ALLOW`` under a yes or route
    (a)'s fresh ``CONFIRM`` (§4:7).

    **What a row resolves is labelled a ruling, on every row.** ADR-0186 §7 asks that
    a decision whose ``resolves`` is set *name* the ``CONFIRM`` it answers, and the
    row names it by id. Whether that ``CONFIRM`` was ever put to you as a question is
    not on the row: route (a) resolves the confirm ruled fresh in your yes's activation
    (§4:7), and where ``ActionPolicy.resolve`` refuses it the ``DENY`` names no
    approval (§4:3), so the absence of one establishes nothing (#3073).

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
    approval = decision.approval
    _print(
        f"  {_decision_headline(decision.ruling.outcome, names_a_yes=approval is not None)} "
        f"[dim]{_decided_at(decision.decided_at)}[/] [dim]{_safe(decision.id)}[/]"
    )
    _print(
        f"  [bold]Tool:[/] {_safe(decision.tool.id)} "
        f"[dim](capability {_safe(decision.tool.capability)})[/]"
    )
    _print(f"  [bold]Why:[/] {_safe(decision.ruling.reason)}")
    _print(
        f"  [bold]Digest:[/] {_safe(decision.parameters_digest)} "
        "[dim](a digest, never the arguments)[/]"
    )
    if decision.resolves is not None:
        after_a_yes = (
            " [dim](ruled again after your yes; the question your yes answered is named below)[/]"
            if approval is not None
            else ""
        )
        _print(f"  [bold]Resolves the ruling:[/] {_safe(decision.resolves)}{after_a_yes}")
    if approval is not None and decision.approved_part is not None:
        _render_approval(approval, decision.approved_part)
    if decision.ruling.outcome is PermissionOutcome.ALLOW:
        _print(f"  {_authorisation_line(decision)}")
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
        _print("[yellow]Nothing recorded.[/] No ruling has been made yet.")
        return
    _print(f"[bold]{len(recorded)}[/] ruling(s), newest ruling first:\n")
    for decision in recorded:
        _render_decision(decision)
    if len(recorded) == limit:
        _print(
            f"[dim]Showing {limit}. Ask for more with --limit; there is no total "
            "count, and 'assistant export-decisions' writes the whole record.[/]"
        )
    _print(
        "[dim]Each row is a ruling that was made. It does not say the ruling still "
        "stands, that a grant is current, that an account is still connected, or that "
        "the tool is still registered under the identifier above — and it does not say "
        "the call ever ran: this record bounds what was decided, not what was carried "
        "out.[/]"
    )
    _print(
        "[dim]A ruling that needed your yes and the answer to it are two rows. An answer "
        "can fall outside this page, so a ruling with nothing answering it here is a fact "
        "about the page and not about the ruling.[/]"
    )
    _print(
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
    _print(f"  {word} [dim]{_checked_at(record.checked_at)}[/] [dim]{_safe(record.id)}[/]")
    _print(f"    [dim]{ending}[/]")
    _print(f"  [bold]Source:[/] {_safe(record.source)} [dim](as the reader declares it)[/]")
    _print(f"  [bold]Read for:[/] {_scope_phrase((record.use,))}")
    _print(f"  [bold]Under grant:[/] {_read_grant_line(record)}")
    _print(
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
        _print("[yellow]Nothing recorded.[/] No attempt to read a source is in this record.")
        _print(
            "[dim]That is not a claim that nothing was ever read: this record states "
            "what it holds, the oldest attempts are dropped as it fills, and a fault "
            "can leave a read with no row.[/]"
        )
        return
    _print(f"[bold]{len(recorded)}[/] read attempt(s), newest recorded first:\n")
    for record in recorded:
        _render_read(record)
    if len(recorded) == limit:
        _print(
            f"[dim]Showing {limit}. Ask for more with --limit; there is no total "
            "count, and 'assistant export-reads' writes every attempt still held.[/]"
        )
    _print(
        "[dim]Each row is an attempt that was made. It does not say the source is "
        "still allowed, what you allow it for now, or that the grant named above "
        "still exists — 'assistant granted' is what states that.[/]"
    )
    _print(
        "[dim]What a source returned is counted here and never shown: this record "
        "holds no content at all. And a row says what was attempted, not what came "
        "of it: what any use then did with a reading is a different record.[/]"
    )
    _print(
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
    _print(f"  {kind} [dim]{_recorded_at(row.recorded_at)}[/] [dim]{_safe(row.id)}[/]")
    _print(f"    [dim]{states}[/]")
    _print(
        f"  [bold]Tool:[/] {_safe(recorded.tool)} [dim](capability {_safe(recorded.capability)})[/]"
    )
    _print(
        f"  [bold]Outbound call:[/] {'yes' if recorded.egress_call else 'no'} "
        "[dim](whether the ruling this row names carried an outbound binding; "
        "who or where is not on this row)[/]"
    )
    _print(
        f"  [bold]Under authorisation:[/] {_safe(row.decision_id)} "
        "[dim](what it cited then; it is not looked up now)[/]"
    )
    if row.outcome is not None:
        word, ending = _invocation_outcome(row.outcome, egress_call=recorded.egress_call)
        _print(f"  [bold]Ended:[/] {word} [dim]— {ending}[/]")
        if row.outcome is not ToolOutcome.SUCCEEDED:
            _print(f"  [bold]Failure kind:[/] {_invocation_failure_kind(row)}")
        # A completion always carries one; the model refuses one without
        # (``ToolInvocation._is_a_claim_or_a_completion``).
        if row.incurred_cost is not None:
            _print(f"  [bold]Cost:[/] {_incurred_cost(row.incurred_cost)}")
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
        _print(f"[bold]{name}[/]")
        _print(f"  [dim]from {opened}[/]")
        _print(f"  [dim]up to (not including) {closed}[/]")
        if total.currency is None:
            _print("  [dim]No spend currency is configured, so I am not keeping a total.[/]")
        elif total.accounted is None:
            _print(
                f"  [yellow]Not measurable.[/] Something in this period has no price I may "
                f"add — a call still in flight, or one whose cost nobody reported — so I "
                f"will not state a {total.currency} figure I would be inventing."
            )
            if total.ceiling is not None:
                _print(
                    f"  [red]Nothing further will run in this period[/] while that is so: "
                    f"there is a ceiling of {total.ceiling} {total.currency} here and I "
                    f"cannot tell whether a call would cross it."
                )
            else:
                _print(
                    "  [dim]Nothing is being refused on that account: you have set no "
                    "ceiling for this period.[/]"
                )
        else:
            stated = f"  [bold]{total.accounted} {total.currency}[/]"
            if total.ceiling is None:
                _print(f"{stated} [dim]— no ceiling set for this period.[/]")
            else:
                _print(f"{stated} [dim]of a ceiling of[/] {total.ceiling} {total.currency}")
        console.print()
    _print(
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
        _print("[yellow]Nothing recorded.[/] No act on an authorisation is in this record.")
        _print(
            "[dim]That is not a claim that nothing was ever attempted: this record "
            "states what it holds, and a fault can leave an act with fewer rows than "
            "it made.[/]"
        )
        return
    _print(f"[bold]{len(recorded)}[/] row(s), newest recorded first:\n")
    for row in recorded:
        _render_invocation(row)
    if len(recorded) == limit:
        _print(
            f"[dim]Showing {limit}. Ask for more with --limit; there is no total "
            "count, and 'assistant export-invocations' writes the whole record.[/]"
        )
    _print(
        "[dim]One attempt is up to two rows — a call begun, and how a call finished. "
        "They are two rows and not one, and a row with no partner on this page is a "
        "fact about the page: the other half may be further back.[/]"
    )
    _print(
        "[dim]A row says I spent an authorisation and attempted a call. It does not "
        "say the authorisation still stands, that the tool is still registered under "
        "the identifier above, or that anything is still running.[/]"
    )
    _print(
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
    _print(f"About to connect the account [bold cyan]{_safe(identity)}[/]{where}.\n")
    _print(
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
    _print(f"[red]That credential cannot be used:[/] {_safe(str(exc))}. Nothing was sent.")


def _render_connected(verb: str, record: ConnectedAccount) -> None:
    """Report a completed provisioning act, with the reference the hub minted.

    An act returns only once ADR-0148 §6's **third** write has landed, so this is
    the one place on the surface where a connection may be called live — and the
    record carries ``ACTIVE`` by contract (ADR-0151 §7).

    The reference is printed prominently because it is the whole handle: §3 minted
    it inside the act, the user did not choose it, and every act after this one is
    performed against a value they read back off a listing.
    """
    _print(
        f"[green]{verb}.[/] [bold cyan]{_safe(record.identity)}[/] is connected, "
        f"at revision {record.revision}."
    )
    _print(f"  Its reference is [bold]{_safe(record.reference)}[/]")
    _print_hint(
        "  [dim]Read it back any time with 'assistant connections'. Replace its "
        "credential with 'assistant reconnect', or end it with "
        f"{_reference_hint(record.reference, 'assistant disconnect')}[/]"
    )
    _print(
        "\n[dim]This is a connection, not a permission: it authorises nothing on its "
        "own. What I am allowed to read is 'assistant granted'.[/]"
    )


def _render_keyless_intent(identity: str) -> None:
    """Show the name of a keyless connection as part of the act (ADR-0325 §4:5).

    :func:`_render_connection_intent`'s display, for an act with no credential:
    there is no field beside the name for a secret to be pasted into, so the
    sentence does not warn about one, and it says that no key is involved so a
    person who meant ``connect`` sees that before anything is written. Neutralised
    for this terminal by :func:`_safe`, and echoed nowhere else (ADR-0149 §3).
    """
    _print(f"About to connect [bold cyan]{_safe(identity)}[/] as a source that needs no key.\n")
    _print(
        "[dim]That is the name I will record and show you, exactly as you typed it — "
        "I normalise nothing. A source that needs a key is 'assistant connect'.[/]\n"
    )


def _render_refused_keyless_name(exc: UnusableIdentityError) -> None:
    """Report a keyless name refused before anything was sent (ADR-0325 §4:3).

    :func:`_render_provisioning_outcome`'s sentence for the same refusal on
    ``connect``, less its clause about a credential, which this act has none of.
    The message is :func:`~ai_assistant.wire.codec.usable_identity`'s, which names
    neither the value nor its length.
    """
    _print(
        "[red]The keyless connection is known not to have landed[/] — I refused the "
        f"name before anything was sent: {_safe(str(exc))}."
    )


def _render_keyless_connected(record: ConnectedAccount) -> None:
    """Report a completed keyless act, with the reference the hub minted (ADR-0325 §3:5).

    :func:`_render_connected`'s report, with the name shown back byte for byte as
    the act returned it (§4:5), and with no hint to replace a credential the
    connection does not hold.
    """
    _print(
        f"[green]Connected.[/] [bold cyan]{_safe(record.identity)}[/] is connected with "
        f"no key, at revision {record.revision}."
    )
    _print(f"  Its reference is [bold]{_safe(record.reference)}[/]")
    _print_hint(
        "  [dim]Read it back any time with 'assistant connections', or end it with "
        f"{_reference_hint(record.reference, 'assistant disconnect')}[/]"
    )
    _print(
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
    _print(
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
    _print(
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
            _print(
                f"[red]The {act} is known not to have landed[/] — I refused the "
                f"account name before anything was sent, so your credential never "
                f"left this machine: {_safe(str(exc))}."
            )
        case UnknownConnectionError():
            _print(
                f"[red]The {act} is known not to have landed[/] — I hold no "
                f"connection under {named}, so nothing was written. "
                "'assistant connections' lists the references I do hold."
            )
        case DisplacedProvisioningError():
            _print(
                f"[red]The {act} was not performed.[/] Another act took {named} over "
                "while this one was running, so no record I wrote is that "
                "reference's live one. Nothing was rolled back, and this act may "
                "have left an entry and a credential of its own that no call reads — "
                "disconnecting that reference removes them. Do not simply run it "
                "again; read what is connected first."
            )
        case IncompleteProvisioningError():
            _print(
                f"[yellow]The {act} did not complete.[/] The reference {named} "
                "[bold]exists[/] — I wrote its record — and the credential you gave me "
                "was never put into use, so it will not become the live one. This "
                "call did not leave things as they were. Run the act again on that "
                "reference, or disconnect it; both are safe."
            )
        case ProvisioningOutcomeUnknownError():
            _print(
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
    _print(f"[green]{landed}[/]")
    _print(
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
    _print(
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
    _print(
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
        _print(
            f"[dim]I could not read the state of {_safe(reference)}, so I am not "
            "saying. Try 'assistant connections'.[/]"
        )
        return
    if state is None:
        _print(
            f"I read the store: nothing is connected under [bold]{_safe(reference)}[/] right now."
        )
        return
    _print(
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
        _print(
            "[yellow]Nothing is connected.[/] 'assistant connect' adds an account; "
            "it is a different question from 'assistant granted', which is what I am "
            "allowed to read."
        )
        return
    _print(f"[bold]{len(connected)}[/] connection(s):\n")
    for record in connected:
        _print(f"  [bold cyan]{_safe(record.identity)}[/]")
        _print(f"    [dim]{_safe(record.reference)}[/] — revision {record.revision}")
        if record.state is ProvisioningState.ACTIVE:
            _print(f"    [green]{_connection_state_phrase(record.state)}[/]")
        else:
            _print(f"    [yellow]{_connection_state_phrase(record.state)}[/]")
            _print(
                "    [yellow]Nothing is in progress and nothing will finish it.[/] "
                "Run the act again with 'assistant reconnect', or end it below."
            )
        _print_hint(
            f"    [dim]end it with {_reference_hint(record.reference, 'assistant disconnect')}[/]"
        )
        console.print()
    _print(
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
        _print("[yellow]Nothing recorded.[/] No connection has been made or ended.")
        return
    _print(f"[bold]{len(acts)}[/] act(s), in the order I recorded them, newest first:\n")
    for act in acts:
        if act.account is None:
            _print(f"  [bold]disconnected[/] [dim]{_safe(act.reference)}[/]")
        elif act.account.state is ProvisioningState.ACTIVE:
            _print(
                f"  [bold]connected[/] [bold cyan]{_safe(act.account.identity)}[/] "
                f"[dim]{_safe(act.reference)}[/]"
            )
        else:
            # A row is what an act *reached*, never what a reference is now
            # (ADR-0151 §9), and "connected" over an act that never activated would
            # be that claim in one word. What the state says here is how far this
            # act got, which is the whole of what the row carries.
            _print(
                f"  [bold]tried to connect[/] [bold cyan]{_safe(act.account.identity)}[/] "
                f"[dim]{_safe(act.reference)}[/] — [yellow]the act never completed[/]"
            )
        _print(f"    [dim]revision {act.revision}[/]")
    if len(acts) == limit:
        _print(f"\n[dim]Showing {limit}. Ask for more with --limit; there is no total count.[/]")
    _print(
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
    _print(
        f"[green]Disconnected.[/] [bold cyan]{_safe(record.identity)}[/] was live at "
        f"revision {record.revision}; no live record names any credential for "
        f"[bold]{_safe(record.reference)}[/] any more."
    )
    _print(
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
    _print(
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
        _print(f"[red]The assistant hub is not reachable:[/] {_safe(str(exc))}", to=target)
        return
    _print(f"[red]Error:[/] {_safe('; '.join(_leaf_messages(exc)))}", to=target)


def _leaf_messages(exc: BaseException) -> list[str]:
    """The messages of ``exc``, flattening a (possibly nested) exception group."""
    if isinstance(exc, BaseExceptionGroup):
        return [message for sub in exc.exceptions for message in _leaf_messages(sub)]
    return [str(exc)]


if __name__ == "__main__":
    app()

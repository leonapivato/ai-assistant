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

v1 renders the *final* state of each call; streaming is deferred (ADR-0042 §5).
"""

from __future__ import annotations

import asyncio
import math
import re
import shlex
import sys
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, NamedTuple, assert_never

import typer
from rich.console import Console
from rich.markup import escape

from ai_assistant import __version__
from ai_assistant.core.config import load_settings
from ai_assistant.core.errors import AssistantError
from ai_assistant.core.logging import configure_logging
from ai_assistant.core.types import (
    DEFAULT_NOTIFICATION_REACH,
    AnswerKind,
    BeliefBand,
    ClassReach,
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
    QuestionState,
    QueueOutcome,
    QuietWindow,
    SecretScope,
    StepStatus,
    encodable_text,
)
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
    from collections.abc import Callable, Sequence

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import (
        AnswerOutcome,
        Belief,
        BeliefSummary,
        Confirmation,
        ConversationDigest,
        ConversationSummary,
        GrantableSource,
        HeldNotification,
        IngestSummary,
        LearnOutcome,
        NotificationCandidate,
        ObservationReport,
        ObservedProposal,
        Question,
        QueuedQuestion,
        SourceGrant,
        StepOutcome,
        TurnOutcome,
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
def learn(
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
        help="The conversation to observe. Defaults to the most recently active one.",
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

    A source can have one grant at a time. To change what a grant covers, revoke it
    and grant again; both acts stay on the record.
    """
    code = asyncio.run(_grant_source(source, scope=scope, assume_yes=yes))
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
    that it still stands — use ``assistant sources``, which asks me directly.
    """
    code = asyncio.run(_list_grants(limit=limit))
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
    credential = (
        sys.stdin.readline().strip()
        if credential_stdin
        else typer.prompt("Credential", hide_input=True)
    )
    code = asyncio.run(_store_device_enrolment(hub_identity, credential))
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


async def _store_device_enrolment(hub_identity: str, credential: str) -> int:
    """Load settings, store both values, and say what happened (ADR-0124 §6).

    One error boundary spanning every stage that can fail, as every other command
    here has (ADR-0042 §7): a keyring that is absent or locked, a value this device
    will not hold, and a configuration that will not load are all rendered and
    mapped to a non-zero exit code rather than escaping as a traceback.
    """
    try:
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
    seven databases and the API the only door, and the ``interfaces -> app`` import
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
    try:
        engine = await _open_engine()
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR

    return await _drive_turn(
        engine, utterance, timeout=timeout, approver=approver, conversation_id=conversation_id
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


async def _learn_feedback(
    content: str,
    *,
    kind: FeedbackKind,
    memory_kind: MemoryKind | None,
    subject: str | None,
    about_person: str | None,
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
    """
    event = FeedbackEvent(
        kind=kind,
        memory_kind=memory_kind,
        content=content,
        subject=subject,
        about_person=about_person,
        created_at=_utcnow(),
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


async def _drive_turn(
    engine: AssistantEngine,
    utterance: str,
    *,
    timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, relayed to the façade (ADR-0029 §4)
    approver: Callable[[Confirmation], bool],
    conversation_id: str | None = None,
) -> int:
    """Converse, render, and relay a confirmation if the engine parks one.

    A turn drives at most one step today (ADR-0042 §3), so at most one
    confirmation can arise; ``resume`` resolves it to ``EXECUTED`` or ``DENIED``.
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
    try:
        outcome = await engine.converse(utterance, timeout=timeout, conversation_id=conversation_id)
        failed = _render_turn(outcome)
        step = outcome.step
        if step is not None and step.confirmation is not None:
            approved = approver(step.confirmation)
            outcome = await engine.resume(
                step.confirmation.token, approved=approved, timeout=timeout
            )
            failed = _render_turn(outcome)
    except (AssistantError, TransportError) as exc:
        _render_error(exc)
        return _EXIT_ERROR
    _render_conversation_footer(outcome)
    return _EXIT_ERROR if failed else _EXIT_OK


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
    console.print(
        f"[green]Granted.[/] I may now read [bold]{_safe(recorded.source)}[/] for "
        f"{_scope_phrase(recorded.scope)}. Withdraw it any time with "
        f"'assistant revoke {_safe(recorded.source)}'."
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
    # **Both lines say "due", never "done", and the tense is ADR-0130 §6's** rather
    # than caution. The write is atomic with a `reconsider_at` stamp and stops there:
    # "the existing job picks them up on its next run", and §5 makes that floor a
    # floor — "a late reconsideration is not a fault". So a record is still `HOLD` when
    # this message prints. Claiming it had already been re-ruled would have the user
    # who raised a class read the silence that follows as the act having failed, on
    # the one surface built because that act had no door at all (#979).
    #
    # The `interrupt` line is qualified a second time, because reach is not the only
    # condition (§5): a held record that named no moment it stops mattering re-holds
    # on `PERISHABLE`, which §6 says "is reached by no setting", so for those the
    # sweep changes nothing whenever it runs.
    if asked.reach is NotificationReach.INTERRUPT:
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
    return _EXIT_OK


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


def _safe(value: str) -> str:
    r"""Neutralise tool-supplied data for this terminal (ADR-0042 §4).

    "Safe" is target-specific, so the engine carries values verbatim and each
    adapter escapes for its own output. Here that means two things: replace
    non-printable control characters (an ANSI escape like ``\\x1b[2J`` a terminal
    would act on) with the replacement character, and escape Rich markup so a
    value like ``[red]`` is shown, not interpreted.
    """
    cleaned = "".join(ch if ch.isprintable() or ch in "\t " else "�" for ch in value)
    return escape(cleaned)


def _render_turn(outcome: TurnOutcome) -> bool:
    """Render one turn's plan, degraded-memory notice, and step outcome.

    ``outcome.turn`` is ``None`` on a resume driven from a **recovered** park
    (ADR-0052 §3) — a confirmation reconstructed from durable state after a restart
    has no live turn to render — so only the step is shown there. The action itself
    was already shown from the recovered confirmation before the user answered.

    Returns:
        Whether a step ran and did not succeed, which the caller folds into the
        process exit code (#531).
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
    if turn is not None:
        if turn.memory_degraded:
            console.print(
                "[yellow]Note:[/] personal memory was unavailable, so this answer is generic."
            )
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


def _render_disposition(disposition: Disposition, tool_id: str | None) -> None:
    """Render the permission gate's verdict on the driven step (ADR-0042 §3).

    **Only the verdict.** ``EXECUTED`` says the call was authorised and handed to
    the executor, not that the executor succeeded — its own documentation delegates
    that downward — so :func:`_render_step` consults the step's record before
    reaching for this, and "Done." is printed only for a step that really is done
    (ADR-0084 §8).
    """
    tool = _safe(tool_id) if tool_id is not None else "the selected tool"
    messages = {
        Disposition.EXECUTED: f"[green]Done.[/] Ran {tool}.",
        Disposition.DENIED: "[red]Declined.[/] The policy did not permit this action.",
        Disposition.NO_CAPABLE_TOOL: "[dim]No tool is available for this step yet.[/]",
        Disposition.AMBIGUOUS_CAPABILITY: "[dim]Several tools could do this; none was chosen.[/]",
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
        console.print(f"  [dim]1.[/] Dispose of it: assistant forget-question {_safe(question.id)}")
        console.print(
            "  [dim]2.[/] Check 'assistant beliefs', and use 'assistant learn' again if "
            "the correction is missing."
        )
    else:
        console.print(
            f"  [dim]Answer with:[/] assistant answer {_safe(question.id)} "
            f"--accept  [dim]|[/]  --reject"
        )
    _render_successor(question)


def _render_retirements(question: Question) -> None:
    """Render exactly what accepting a question would retire (ADR-0078 §8).

    A conflict that has been retired since the question was asked does not resolve
    and is rendered as **no longer held** rather than omitted: the user should be told
    that the thing they would be overruling is already gone. Omitting it would
    understate the answer's scope in one direction and overstate it in the other.
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
        else:
            console.print(
                f"    - {_safe(retirement.content)} [dim]({_safe(retirement.record_id)})[/]"
            )


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
            console.print(
                f"  [dim]Here is the follow-up:[/] [bold cyan]{identifier}[/] "
                f"[dim](assistant answer {identifier} --accept)[/]"
            )
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


def _why_derived(belief: Belief | BeliefSummary) -> str:
    """Why a **derived** belief is held: the count, what is gone, and the ceiling.

    Split out of :func:`_why` so the ceiling is appended **once, on every path**
    rather than per branch. That is the structural point: ADR-0107 §5 owes the
    ceiling wherever this surface renders a citation count, and this branch renders
    one in all four of its states — including the state that renders it as *none*.
    A per-branch append would let a fifth state be added later with the clause
    forgotten, and the belief that elided nine hundred citations is exactly the one
    that would go unmentioned.

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
    return head + ceiling


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
    * **Attested** — it is named as someone else's report, so it reads as neither
      the user's word nor the assistant's inference, and the line says outright that
      ``Last revised`` is the assistant's clock rather than the source's.

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

    **The attested line states a limit of this surface, never a limit of the store.**
    Which source spoke, and when, are *held*: an attested belief carries an
    :class:`~ai_assistant.core.types.Attestation` by construction, since
    :class:`~ai_assistant.core.types.Provenance` makes one mandatory exactly on this
    band (ADR-0092 §1). What drops them is the projection — neither
    :class:`~ai_assistant.core.types.Belief` nor
    :class:`~ai_assistant.core.types.BeliefSummary` has anywhere to put one (**#754**;
    its predecessors #711 and #568 are both closed, the second by ADR-0107, whose §10
    keeps this question open by name). So "not recorded" would err in the direction
    ADR-0073 §4 forgives least: a user auditing what is held about them would read it
    as "you did not keep it", the inverse of the truth, on the one band whose whole
    purpose is provenance. ADR-0098 §8 reads this branch as evidence that the belief
    surface carries no attestation — and it still is, in words that are also true of
    the store.
    """
    match belief.band:
        case BeliefBand.ASSERTED:
            return "you told me, and your own word is the whole of it."
        case BeliefBand.DERIVED:
            return _why_derived(belief)
        case BeliefBand.ATTESTED:
            return (
                "a source you connected reported it — neither your word nor my inference. "
                "I recorded which source, and when it said so, but cannot show them here, "
                "so 'Last revised' below is when I changed my mind and not when the "
                "source spoke."
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

    The ``Why`` line reads only the counts, which both types carry — which is why
    the two views share this renderer rather than one of them needing its own.

    Engine-supplied text — the content and the id — is neutralised for this
    terminal like any other (``_safe``, ADR-0042 §4). The band and kind are this
    system's own closed vocabularies, not carried data.
    """
    console.print(
        f"\n  [bold cyan]{belief.band.value}[/] · {belief.kind.value} · "
        f"confidence {belief.confidence:.2f}"
    )
    console.print(f"  {_safe(belief.content)}")
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
        console.print(
            "\n  [yellow]It is already granted[/] for "
            f"{_scope_phrase(chosen.live.scope)}. A source has one grant at a time, "
            "so this will be refused — withdraw the current one first with "
            f"'assistant revoke {_safe(chosen.source)}'."
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
    ``assistant sources``.
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
        "\n[dim]Whether a source is granted *now* is 'assistant sources' — a record "
        "here says an act happened, not that it still stands.[/]"
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
        console.print(
            "  [yellow]Its id or its class holds characters this terminal cannot "
            "show[/], so there is no command here to copy — one written from what is "
            "on screen would name something else. The 'dismiss' and 'tune' commands "
            "still take them, given the exact bytes."
        )
        return
    console.print(f"  [dim]Deal with it:[/] assistant dismiss {_safe(shlex.quote(record.id))}")
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
    console.print(
        f"  [dim]Tune the class:[/] assistant tune --class "
        f"{_safe(shlex.quote(notification_class))} --reach {wanted.value}"
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

    Args:
        value: The value a printed command would carry.

    Returns:
        Whether the value survives being displayed.
    """
    return _safe(value) == escape(value)


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


def _render_confirmation(confirmation: Confirmation) -> None:
    """Render a parked action so a person can judge it (ADR-0042 §4)."""
    console.print("\n[bold yellow]Confirmation required[/]")
    console.print(f"  Tool: {_safe(confirmation.tool_id)} — {_safe(confirmation.tool_description)}")
    if confirmation.parameters:
        console.print("  With:")
        for key, raw in confirmation.parameters.items():
            console.print(f"    {_safe(str(key))} = {_safe(str(raw))}")
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


def _render_error(exc: Exception) -> None:
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
    """
    if isinstance(exc, TransportError):
        console.print(f"[red]The assistant hub is not reachable:[/] {_safe(str(exc))}")
        return
    console.print(f"[red]Error:[/] {_safe('; '.join(_leaf_messages(exc)))}")


def _leaf_messages(exc: BaseException) -> list[str]:
    """The messages of ``exc``, flattening a (possibly nested) exception group."""
    if isinstance(exc, BaseExceptionGroup):
        return [message for sub in exc.exceptions for message in _leaf_messages(sub)]
    return [str(exc)]


if __name__ == "__main__":
    app()

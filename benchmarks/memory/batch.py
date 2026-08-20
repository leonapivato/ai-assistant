"""Answer and judge a whole run through the Batches API (ADR-0143).

**Why the harness is allowed to be here at all.** ADR-0143 §8 has a consumer depend
on the ``BatchCompleter`` Protocol and obtain an instance "by construction in a
composition root it owns ... its own root for a consumer outside ``ai_assistant``".
This harness is that consumer and :mod:`benchmarks.memory.wiring` is that root. What
is imported here is the *contract* and the ``core`` types; the vendor-backed
implementation is reached through
:func:`ai_assistant.models.batch.anthropic_batch_completer`, which exists because the
constructor it wraps needs a client no consumer outside the package may name.

**What batches and what cannot.** Ingestion stays serial and is not on this axis:
``ObservationStage`` reads the conversation's most recent window, so every pass
depends on the writes the pass before it made. Retrieval does not batch either — it
is local work against this process's own SQLite. What is left is the two model calls
per question, answering and judging, which is roughly 60% of a scored run's spend and
all of its serial round trips.

**The order is: retrieve everything, then submit once, then wait.** Not because
waiting is cheap but because ADR-0143 §2 makes the wait the caller's loop, and a
caller that interleaved submissions with retrieval would hold several paid jobs at
once while doing work that can fail. One batch is one thing to lose.

**A submitted batch is written to disk before anything waits on it.** That is
ADR-0060's rule applied to money: a batch is remote, outlives the coroutine, is being
billed, and cannot be released by returning. §2 hands the handle back before any
waiting *precisely* so it can be recorded, and recording it only in memory would
discharge that until the process died. :func:`submit_and_settle` calls its
``on_batch`` before its first ``poll``, and the caller appends to ``batches.jsonl``
there.

**A failed item is a recorded outcome and never a silent empty answer.** ADR-0143 §4
returns exactly one outcome per submitted item and §5 makes a failure a value rather
than an exception, so an expired, cancelled or failed item becomes an ``ungraded``
row naming what happened — never an empty string that would grade as an abstention
and be counted, in #1029's P7, as the system declining to answer.

**The provider's own words are dropped, as everywhere else in this harness.**
``BatchItemFailure.detail`` is text a provider wrote and
:mod:`benchmarks.memory.spend` states the rule: the match is read, the decision is
recorded, the text is dropped. Only :class:`~ai_assistant.core.types.BatchFailureKind`
— our own enum — reaches a record.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from time import monotonic
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import BatchOutcomeKind, BatchRequest, BatchState
from benchmarks.memory.grade import Grading, Verdict, grading_from_reply, judge_messages
from benchmarks.memory.records import BatchRef
from benchmarks.memory.spend import RunAbortedError, SpendGuard
from benchmarks.memory.usage import BatchItemUsage, UsagePhase, prompt_chars

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ai_assistant.core.protocols import BatchCompleter
    from ai_assistant.core.types import BatchHandle, BatchItemOutcome
    from benchmarks.memory.answer import RetrievedContext
    from benchmarks.memory.cases import BenchCase, BenchQuestion
    from benchmarks.memory.records import RetrievalTelemetry

__all__ = [
    "ANSWER_BATCH",
    "DEFAULT_POLL_INTERVAL",
    "DEFAULT_POLL_TIMEOUT",
    "ITEM_ID_PATTERN",
    "JUDGE_BATCH",
    "JUDGE_ITEM_SUFFIX",
    "PHASE_BY_BATCH",
    "BatchFile",
    "BatchSession",
    "BatchUsage",
    "PollPolicy",
    "PreparedQuestion",
    "answer_batch",
    "item_id_for",
    "judge_batch",
    "submit_and_settle",
]

#: The two batches a run submits, named in ``batches.jsonl`` and in the manifest.
ANSWER_BATCH: Final = "answer"
JUDGE_BATCH: Final = "judge"

#: Which ledger phase each of the two batches spends on.
#:
#: A mapping rather than a conditional at the one call site, so that a third batch — were
#: one ever added — fails with a ``KeyError`` naming itself rather than quietly acquiring
#: the phase whichever branch happened to be the ``else``. That is the same discipline
#: ``BatchFailureKind``'s disposition tables use, and for the same reason: a new member
#: must not inherit a classification nobody chose.
PHASE_BY_BATCH: Final[Mapping[str, UsagePhase]] = {
    ANSWER_BATCH: UsagePhase.ANSWERING,
    JUDGE_BATCH: UsagePhase.JUDGING,
}

#: How long to wait between polls. A minute, because ADR-0143 §2 makes ``poll`` one
#: bounded exchange and a batch takes tens of minutes: polling faster buys nothing
#: and spends request quota on a question whose answer will not have changed.
DEFAULT_POLL_INTERVAL: Final = 60.0

#: How long to keep polling before giving up on a batch, in seconds. Twenty-six
#: hours: the vendor's processing window is 24, after which an unprocessed item
#: surfaces as an ``EXPIRED`` outcome rather than as a batch that never settles
#: (ADR-0143 §6), so a deadline shorter than the window would abandon batches that
#: were about to become readable. The two hours past it are slack for a provider that
#: closes its window late; a run that reaches this really has hit something other
#: than ordinary latency.
DEFAULT_POLL_TIMEOUT: Final = 26 * 60 * 60.0

#: What distinguishes a question's judge item from its answer item.
#:
#: The two batches carry different work for the same question, and an id that did not
#: say which would be legible to nobody: an operator reading a provider console or
#: ``batches.jsonl`` sees ids and nothing else, and a fetched outcome carries only the
#: id it was submitted under. Suffixing rather than minting a second id keeps the join
#: trivial — strip it, and you have the answer item, which is what ``batch_item_id``
#: records on the row.
#:
#: It is spelled with a hyphen rather than the ``.judge`` it once was because a dot is
#: outside :data:`ITEM_ID_PATTERN` and the vendor refuses the whole batch over one
#: character. Its *length* is load-bearing too: the judge id is the answer id plus this
#: suffix, so it is the judge id that has to fit in 64 characters, and
#: :data:`_ID_PREFIX_CHARS` is derived from this string's length so that lengthening it
#: shortens the readable half instead of overflowing the ceiling.
JUDGE_ITEM_SUFFIX: Final = "-judge"

#: What Anthropic's Message Batches API accepts as a ``custom_id``, which is what
#: ADR-0143's ``item_id`` is submitted as (``models/batch.py``'s ``_request_for``).
#:
#: **A vendor constraint the caller has to satisfy, because nothing between here and
#: the wire will.** ADR-0143 §3 is explicit that the seam "never mints, rewrites or
#: normalises an ``item_id``", and §9 chose ``NonBlankEncodableText`` over
#: ``Identifier`` precisely so an id is carried byte-for-byte — so an id this harness
#: mints is the id the provider validates. The first live ``--phase batch`` submission
#: found that out: the whole batch was refused with
#: ``requests.0.custom_id: String should match pattern '^[a-zA-Z0-9_-]{1,64}$'``, on
#: the dot this module used to put between the two halves and again in ``.judge``, and
#: on a length that could reach 66 before the judge suffix pushed it to 72. Nothing was
#: charged, and nothing else in the run had failed: an hour of retrieval was thrown
#: away over the id format alone.
#:
#: It is stated here rather than enforced in ``models/batch.py`` because it is *this*
#: vendor's rule and that module is the only place that knows it — a check there is
#: issue #1207's question, not this constant's.
ITEM_ID_PATTERN: Final = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

#: The ceiling :data:`ITEM_ID_PATTERN` imposes, as a number the budget below can do
#: arithmetic on.
_ID_MAX_CHARS: Final = 64

#: How much of the digest of the whole pair is appended. Sixty-four bits of SHA-256,
#: which is what makes distinct pairs distinct ids once the readable halves have been
#: truncated and sanitised into each other.
_ID_DIGEST_CHARS: Final = 16

#: How much of a sanitised key survives into an ``item_id``, per half.
#:
#: **Derived rather than chosen, so the ceiling cannot be overflowed by editing
#: something else.** The longest id this module submits is a *judge* id, which is
#: ``<half>-<half>-<digest>`` plus :data:`JUDGE_ITEM_SUFFIX`: two separators, the
#: digest, and the suffix are fixed costs, and what is left over is split between the
#: two readable halves. Twenty characters each, at present — enough for a LoCoMo
#: ``sample_id`` and its question ordinal whole, and enough of a LongMemEval hash to
#: pick a case out of a provider console.
_ID_PREFIX_CHARS: Final = (
    _ID_MAX_CHARS - len(JUDGE_ITEM_SUFFIX) - _ID_DIGEST_CHARS - len("--")
) // 2

#: Everything :data:`ITEM_ID_PATTERN` does not admit, for the substitution below.
_ID_UNSAFE: Final = re.compile(r"[^a-zA-Z0-9_-]")


def item_id_for(case_key: str, question_id: str) -> str:
    """Name one question's batch item, injectively.

    **The id is the only thing that matches an outcome back to a question**
    (ADR-0143 §4: "a caller matches an outcome to its request by ``item_id`` and never
    by position"), so two questions sharing one would silently graft one case's answer
    onto another's record — the same hazard
    :func:`~benchmarks.memory.run.case_dir_name` exists for, one level up, and it is
    solved the same way. Sanitising alone is not injective: ``("a/b", "c")`` and
    ``("a_b", "c")`` sanitise alike. So the id is a readable prefix of each half
    *plus a digest of the exact pair*, and the digest is what makes distinct pairs
    distinct ids.

    **The digest hashes a length-prefixed encoding, not a delimited one**, because a
    delimiter is only unambiguous while the payload cannot contain it. Joining the two
    halves on a ``NUL`` — as this did — collides the moment a key holds one: the pair
    whose case key is ``a``-``NUL``-``b`` with question id ``b``, and the pair whose
    case key is ``a`` with question id ``b``-``NUL``-``b``, hash the same bytes. A
    corpus key is a JSON string, and JSON admits ``NUL``. Two questions sharing an id
    is not a mild defect here: ``submit`` refuses the whole batch on a duplicate
    (ADR-0143 §3), after the retrieval phase has already run and cannot be replayed
    cheaply. Prefixing the first half's length makes the encoding decodable, and so
    injective over any pair of strings at all rather than over the well-behaved ones.

    ``surrogatepass`` is on that encode for the same reason the length prefix is
    there: to make "any pair of strings" true rather than nearly true. ``json.loads``
    turns a ``u+D800`` escape into a lone surrogate — a perfectly ordinary Python
    ``str`` that both loaders' string checks admit — and plain UTF-8 raises
    ``UnicodeEncodeError`` on it, which would abandon a run at id-minting time over a
    character the id was going to replace with ``_`` anyway. The codec is injective
    over the whole of ``str``, so nothing about the paragraph above weakens.

    The readable prefix is not decoration. A run that dies between ``submit`` and
    ``fetch`` leaves a batch whose ids are all anyone has to work from until
    ``records.jsonl`` exists, and an operator reading ``batches.jsonl`` against the
    provider's console should be able to see which case is which.

    ``item_id`` is ``NonBlankEncodableText`` and is carried back byte-for-byte
    (ADR-0143 §9 chose it over ``Identifier`` for exactly that), so nothing here has
    to survive a normalisation — and nothing here is *given* one either, which is why
    :data:`ITEM_ID_PATTERN` has to be satisfied on this side of the seam. Every
    character outside it becomes ``_``, and each half is truncated to
    :data:`_ID_PREFIX_CHARS` so that the id, **and the judge id built from it**, fit
    the vendor's 64. Note that the substitution is against that pattern rather than
    against :meth:`str.isalnum`, which is true of ``"é"`` and ``"²"``: this is an ASCII
    rule, and a corpus key is not obliged to be ASCII.

    This names a question's **answer** item. Its judge item is this plus
    :data:`JUDGE_ITEM_SUFFIX`, so the two are joinable by stripping and are still
    telling apart in a provider's console, which shows ids and nothing else. Nothing
    this returns can be mistaken for a judge id: an answer id ends in ``-`` followed by
    :data:`_ID_DIGEST_CHARS` hex characters, and ``-judge`` is neither that length nor
    hex.

    Args:
        case_key: The case's key, as its corpus gives it.
        question_id: The question's id within that case.

    Returns:
        One id, unique to the pair, non-blank, and matching :data:`ITEM_ID_PATTERN`.
    """
    readable = _ID_UNSAFE.sub(
        "_", f"{case_key[:_ID_PREFIX_CHARS]}-{question_id[:_ID_PREFIX_CHARS]}"
    )
    digest = sha256(
        f"{len(case_key)}:{case_key}{question_id}".encode(errors="surrogatepass")
    ).hexdigest()[:_ID_DIGEST_CHARS]
    return f"{readable}-{digest}"


@dataclass(frozen=True, slots=True)
class PollPolicy:
    """How long a run waits on a batch, and how often it asks.

    Attributes:
        interval: Seconds between polls.
        timeout: Seconds before the run gives up and stops cleanly. The batch is
            still recorded and still fetchable; what ends is this process's wait.
    """

    interval: float = DEFAULT_POLL_INTERVAL
    timeout: float = DEFAULT_POLL_TIMEOUT

    def __post_init__(self) -> None:
        """Refuse a wait that is not a duration.

        The same shape ``SpendGuard`` and ``Harness`` already check their own bounds
        with, and here for a sharper reason than tidiness: these arrive off a command
        line, where ``--batch-timeout nan`` parses perfectly well as a float and then
        makes every ``monotonic() >= deadline`` false. :func:`_wait_for` would poll a
        submitted, billing batch **forever** instead of stopping cleanly as its own
        docstring promises — the one failure mode a bounded loop exists to rule out.
        Infinity is refused with it: an unbounded wait is a legitimate thing to want
        and is not what this parameter offers, so asking for it here would be asking
        for a promise that is not kept.

        Raises:
            ValueError: If either value is not finite, or is negative. Zero is legal
                for both — ``interval=0`` polls as fast as the provider answers, which
                is what a test wants, and ``timeout=0`` gives up after one poll, which
                is a meaningful way to ask "is it done yet?".
        """
        for name, value in (("interval", self.interval), ("timeout", self.timeout)):
            if not isfinite(value):
                msg = f"{name} must be a finite number of seconds, got {value!r}"
                raise ValueError(msg)
            if value < 0:
                msg = f"{name} must not be negative, got {value}"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PreparedQuestion:
    """One question retrieved for, with its answer still outstanding.

    Everything here is captured at retrieval time, while the case's stores and trace
    store are open — which is the whole reason the type exists. A batched run reads
    its answers back hours after the case that produced them was closed and deleted,
    so anything not carried here is unavailable by the time a record is written.

    Attributes:
        case: The case this question belongs to, carried by reference — one object
            shared by every question of that case, not a copy per question.
        question: The question, carried whole for grading and for the record.
        retrieved: The two reads, the prompt, and the correlation scope.
        telemetry: What the ``RETRIEVAL`` traces said, collected while the case's
            trace store was still open.
        evidence_episode_ids: #1074's join, projected onto this question's pointers.
        ingestion: The case's ingestion summary, denormalised onto every record of
            that case exactly as the synchronous path denormalises it.
    """

    case: BenchCase
    question: BenchQuestion
    retrieved: RetrievedContext
    telemetry: RetrievalTelemetry
    evidence_episode_ids: tuple[tuple[str, ...], ...]
    ingestion: Mapping[str, int | float | str | list[str]]

    @property
    def item_id(self) -> str:
        """The id this question's batch items are submitted and matched back under."""
        return item_id_for(self.case.case_key, self.question.question_id)


#: What a caller does with a batch the provider has just accepted.
type BatchFile = Callable[[BatchRef], None]

#: What a caller does with one settled item's measured usage.
#:
#: **Attribution here has to be explicit, because the batched phase has no "current"
#: question to be inside.** On the synchronous path the run is one question at a time and
#: :class:`~benchmarks.memory.usage.UsageLedger`'s scope is enough; here every question is
#: retrieved for, all of them are submitted at once, and the answers arrive hours later
#: after each case's stores have been closed and deleted. So the item reports its own
#: figures and the caller joins them back by ``item_id``, which is the same join ADR-0143
#: §4 already requires for the outcomes themselves.
type BatchUsage = Callable[[BatchItemUsage], None]


@dataclass(frozen=True, slots=True)
class BatchSession:
    """What both of a run's batches share.

    A bundle rather than six repeated arguments, and the grouping is real: every
    field here is a property of *the run*, fixed before the first batch is built and
    identical for the second. The two per-batch inputs — which batch it is, and what
    is in it — stay arguments, because those are the only things that differ.

    Attributes:
        completer: The seam, typed as the Protocol and never as a concrete class
            (ADR-0143 §8).
        guard: The run's spend ceiling, shared with ingestion so the three seams draw
            on one account.
        run_id: What each batch key is built from, so a provider console and a run
            directory name each other. Never an idempotency key — ADR-0143 §2 is
            explicit that two submits under one key are two batches.
        on_batch: Called with each accepted batch **before anything waits on it**.
        poll: How long to wait and how often to ask.
        announce: Where to print progress for an operator watching a paid run.
        route: The ``"provider:model"`` spec the answering batch goes to — the run's
            answering route, which is what :func:`~benchmarks.memory.wiring.build_batch_completer`
            gives the completer as its default. Carried here because a submission that
            passes no per-batch override has no other way to say where it went, and a
            ledger row reading ``route=""`` would be a measurement nobody could attribute
            to a model. The judge batch names its own route at submission and does not
            read this.
        on_usage: Called once per settled item with what it sent and got back, or
            ``None`` to record nothing. Default ``None`` so a caller assembling a session
            for a test is not obliged to care.
    """

    completer: BatchCompleter
    guard: SpendGuard
    run_id: str
    on_batch: BatchFile
    poll: PollPolicy
    announce: Callable[[str], None]
    route: str = ""
    on_usage: BatchUsage | None = None


def _outcome_failure(outcome: BatchItemOutcome | None) -> str | None:
    """Why this item produced no answer, or ``None`` where it produced one.

    The provider's own ``detail`` is deliberately not read: it is text a provider
    wrote, and this harness records classifications rather than vendor prose
    (:mod:`benchmarks.memory.spend` states the rule). What lands in a record is our
    own :class:`~ai_assistant.core.types.BatchFailureKind`, or the outcome kind.

    Args:
        outcome: The outcome for this item, or ``None`` where none came back.

    Returns:
        A short cause, or ``None`` on a usable success.
    """
    if outcome is None:
        # ADR-0143 §4 promises one outcome per submitted item, and `fetch` refuses a
        # short or duplicate-id results file rather than returning one. So this is
        # unreachable through a conforming implementation — and it is handled anyway,
        # because the alternative is a `KeyError` in the middle of writing records for
        # a run that has already been paid for.
        return "no outcome was returned for this item"
    match outcome.kind:
        case BatchOutcomeKind.SUCCEEDED:
            return None if outcome.message is not None else "batch item carried no message"
        case BatchOutcomeKind.FAILED:
            kind = outcome.failure.kind if outcome.failure is not None else "unknown"
            return f"batch item failed ({kind})"
        case BatchOutcomeKind.EXPIRED:
            return "batch item expired before the provider ran it"
        case BatchOutcomeKind.CANCELLED:
            return "batch item was cancelled"


def _reply_of(outcome: BatchItemOutcome | None) -> tuple[str, str | None]:
    """Split one outcome into the text it carried and why it carried none.

    Args:
        outcome: The outcome, or ``None``.

    Returns:
        The reply stripped and no failure, or ``""`` and the cause.
    """
    failure = _outcome_failure(outcome)
    if failure is not None or outcome is None or outcome.message is None:
        return "", failure
    return outcome.message.content.strip(), None


async def submit_and_settle(
    session: BatchSession,
    *,
    kind: str,
    items: Sequence[BatchRequest],
    model: str | None = None,
) -> dict[str, BatchItemOutcome]:
    """Submit one batch, record it, wait for it, and read its outcomes.

    The whole of ADR-0143 §2's caller-side shape in one place: the ceiling is charged
    before the provider is contacted, the handle is written down before anything waits
    on it, and the wait is this loop over ``poll`` rather than something hidden inside
    an awaitable that a cancellation would take the batch with.

    Args:
        session: The run's seam, ceiling, record and wait.
        kind: :data:`ANSWER_BATCH` or :data:`JUDGE_BATCH`, for the record and the
            batch key.
        items: What to submit. An empty sequence submits nothing and returns nothing,
            because ``submit`` refuses an empty batch (ADR-0143 §3) and a run whose
            every answer was settled without a judge call is a real run.
        model: The ``"provider:model"`` route for this whole batch, or ``None`` for
            the completer's configured default. ADR-0143 §2's per-batch override, and
            the reason it is here: a judge is an instrument and need not be the model
            under test, so its batch goes to *its* route rather than to the answering
            one. §11 defers a per-item override; this is per batch, which is what a
            run needs.

    Returns:
        Every outcome, keyed by ``item_id``.

    Raises:
        RunAbortedError: If the ceiling cannot cover the submission, or if the batch
            has not settled within the session's timeout. In the second case the batch
            is already recorded and its outcomes stay fetchable — what stopped is this
            process's wait, not the job.
        ModelError: If the provider refuses the submission or an exchange fails.
    """
    if not items:
        return {}
    session.guard.charge_many(len(items))
    handle = await session.completer.submit(f"{session.run_id}-{kind}", items, model=model)
    # Before the first poll, and before the announcement: if this process dies in the
    # next instant, the file is what says a paid job exists.
    session.on_batch(BatchRef.of(handle, kind=kind, item_count=len(items)))
    # Here, rather than after the fetch, for the reason the file above is written here:
    # what has happened by this line is that a provider accepted a billable job. A batch
    # that then never settles stops the run cleanly through `RunAbortedError`, which
    # rewrites the manifest — and a ledger that had recorded nothing would leave that
    # manifest describing a run whose largest single act is missing from it.
    #
    # **A `fetch` that raises is a different exit and this does not save it** (#1307): a
    # `ModelError` out of `fetch` leaves `execute_run` past every handler, so no rewrite
    # happens and the on-disk manifest stays the pre-run one — which is the tree's
    # standing treatment of a traceback death (`RunManifest.aborted`: such a run "left no
    # manifest claim either way"), and is why `batches.jsonl` rather than the manifest is
    # the guard for a paid job.
    _report_submitted(session, kind=kind, items=items, model=model)
    session.announce(
        f"submitted {kind} batch {handle.batch_id} ({len(items)} items) under "
        f"issuer {handle.issuer}"
    )
    await _wait_for(session, handle, kind=kind)
    outcomes = await session.completer.fetch(handle)
    settled = {outcome.item_id: outcome for outcome in outcomes}
    _report_replies(session, kind=kind, items=items, outcomes=settled, model=model)
    return settled


def _usage_route(session: BatchSession, model: str | None) -> str:
    """Where this batch actually went.

    Args:
        session: The run's session, holding the answering route the completer defaults to.
        model: The per-batch override, or ``None``.

    Returns:
        The ``"provider:model"`` spec to record against.
    """
    return model if model is not None else session.route


def _report_submitted(
    session: BatchSession,
    *,
    kind: str,
    items: Sequence[BatchRequest],
    model: str | None,
) -> None:
    """Report each item's call and prompt, as soon as the provider has accepted them.

    The near half of the same split :class:`~benchmarks.memory.spend.SpendGuard`'s
    wrapper makes on the synchronous seam: what was sent is recorded before there is any
    answer to record, so nothing about a batch that does not come back is lost.

    Args:
        session: The run's session, for its recorder and its default route.
        kind: :data:`ANSWER_BATCH` or :data:`JUDGE_BATCH`.
        items: What was submitted.
        model: The per-batch route override, or ``None`` for the completer's default.
    """
    if session.on_usage is None:
        return
    phase = PHASE_BY_BATCH[kind]
    route = _usage_route(session, model)
    for item in items:
        session.on_usage(
            BatchItemUsage(
                item_id=item.item_id,
                phase=phase,
                route=route,
                calls=1,
                prompt_chars=prompt_chars(item.messages),
            )
        )


def _report_replies(
    session: BatchSession,
    *,
    kind: str,
    items: Sequence[BatchRequest],
    outcomes: Mapping[str, BatchItemOutcome],
    model: str | None,
) -> None:
    """Report what each submitted item got back, once the batch has settled.

    **Driven off ``items`` rather than off ``outcomes``, and the direction matters.**
    ADR-0143 §4 promises one outcome per submitted item, but an item whose outcome is
    missing, expired, cancelled or failed is exactly the item an operator reading a bill
    most needs to see. Walking the outcomes instead would drop those rows and make a
    partly-failed batch look cheaper than it was — and every such item is already in the
    ledger with its prompt, so this half has to visit the same set to leave them at zero.

    **The message's raw content is measured, not the stripped answer.**
    :func:`_reply_of` strips, because a trailing newline is not part of an answer and
    must not be part of a grading; but it *is* part of what the provider generated and
    billed for. The synchronous seam records ``len(reply.content)`` unstripped, so
    measuring the stripped text here would make the same run's two phases report
    different sizes for the same reply — and phase parity is the property this harness
    is most careful about.

    Args:
        session: The run's session, for its recorder and its default route.
        kind: :data:`ANSWER_BATCH` or :data:`JUDGE_BATCH`.
        items: What was submitted.
        outcomes: What came back, keyed by ``item_id``.
        model: The per-batch route override, or ``None`` for the completer's default.
    """
    if session.on_usage is None:
        return
    phase = PHASE_BY_BATCH[kind]
    route = _usage_route(session, model)
    for item in items:
        outcome = outcomes.get(item.item_id)
        message = outcome.message if outcome is not None else None
        session.on_usage(
            BatchItemUsage(
                item_id=item.item_id,
                phase=phase,
                route=route,
                reply_chars=0 if message is None else len(message.content),
            )
        )


async def _wait_for(session: BatchSession, handle: BatchHandle, *, kind: str) -> None:
    """Poll until the batch has settled, or until the deadline.

    The deadline is checked *after* each poll rather than before the sleep, so a batch
    that settles on the last permitted poll is taken rather than abandoned one call
    short of its own results.

    Args:
        session: The run's seam, wait policy and progress channel.
        handle: The batch to wait on.
        kind: Which batch it is, for the progress line.

    Raises:
        RunAbortedError: If the deadline passes with the batch still pending.
    """
    deadline = monotonic() + session.poll.timeout
    while True:
        status = await session.completer.poll(handle)
        if status.state is BatchState.COMPLETE:
            session.announce(f"{kind} batch {handle.batch_id} settled: {status.total} items")
            return
        session.announce(f"{kind} batch {handle.batch_id}: {status.settled}/{status.total} settled")
        if monotonic() >= deadline:
            msg = (
                f"the {kind} batch {handle.batch_id!r} had settled "
                f"{status.settled} of {status.total} items after "
                f"{session.poll.timeout:.0f}s; stopped waiting. The batch is recorded "
                f"in batches.jsonl and its outcomes remain fetchable under issuer "
                f"{handle.issuer!r}"
            )
            raise RunAbortedError(msg)
        await asyncio.sleep(session.poll.interval)


async def answer_batch(
    session: BatchSession, prepared: Sequence[PreparedQuestion]
) -> dict[str, tuple[str, str | None]]:
    """Answer every prepared question in one batch.

    Args:
        session: The run's seam, ceiling, record and wait.
        prepared: Every question the run retrieved for, across every case.

    Returns:
        Each ``item_id`` mapped to its answer and the reason it has none.
    """
    items = [
        BatchRequest(item_id=one.item_id, messages=list(one.retrieved.messages)) for one in prepared
    ]
    outcomes = await submit_and_settle(session, kind=ANSWER_BATCH, items=items)
    return {one.item_id: _reply_of(outcomes.get(one.item_id)) for one in prepared}


async def judge_batch(
    session: BatchSession,
    pending: Sequence[tuple[str, BenchQuestion, str]],
    *,
    judge_name: str,
    judge_route: str,
) -> dict[str, Grading]:
    """Grade every answer that a judge must actually read, in one batch.

    What is *not* here is the point: an abstention and an unanswerable question are
    settled by :func:`~benchmarks.memory.grade.grading_without_a_call` before this is
    called, so they cost no item. The synchronous judge decides them the same way and
    by the same function, which is what keeps the two phases one measure.

    Args:
        session: The run's seam, ceiling, record and wait.
        pending: ``(item_id, question, answer)`` for each answer needing a judgement.
        judge_name: The label to record on every grading, read off the grader that is
            grading rather than declared beside it.
        judge_route: The ``"provider:model"`` spec to *send* the batch to. Separate
            from ``judge_name`` and taken from the same grader, because the two must
            agree by construction: a batch submitted to the answering route while the
            row records ``model:<judge>`` is a manifest that names a judge which never
            saw the prompt, which is exactly the false provenance ``--judge-model``
            exists to prevent.

    Returns:
        Each **answer** ``item_id`` mapped to its grading — the judge item's own
        suffix is stripped here, so a caller keys everything by one id. A judge item
        that did not come back
        usable is ``UNGRADED`` naming why — never a guess, because a judge that could
        not be read has not graded.
    """
    items = [
        BatchRequest(
            item_id=f"{item_id}{JUDGE_ITEM_SUFFIX}",
            messages=list(judge_messages(question, answer)),
        )
        for item_id, question, answer in pending
    ]
    outcomes = await submit_and_settle(session, kind=JUDGE_BATCH, items=items, model=judge_route)
    graded: dict[str, Grading] = {}
    for item_id, _question, _answer in pending:
        reply, failure = _reply_of(outcomes.get(f"{item_id}{JUDGE_ITEM_SUFFIX}"))
        graded[item_id] = (
            grading_from_reply(reply, judge=judge_name)
            if failure is None
            else Grading(
                verdict=Verdict.UNGRADED,
                abstained=False,
                judge=judge_name,
                detail=f"judge failed: {failure}",
            )
        )
    return graded

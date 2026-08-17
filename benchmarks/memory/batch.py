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
from dataclasses import dataclass
from hashlib import sha256
from math import isfinite
from time import monotonic
from typing import TYPE_CHECKING, Final

from ai_assistant.core.types import BatchOutcomeKind, BatchRequest, BatchState
from benchmarks.memory.grade import Grading, Verdict, grading_from_reply, judge_messages
from benchmarks.memory.records import BatchRef
from benchmarks.memory.spend import RunAbortedError, SpendGuard

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
    "JUDGE_BATCH",
    "JUDGE_ITEM_SUFFIX",
    "BatchFile",
    "BatchSession",
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
JUDGE_ITEM_SUFFIX: Final = ".judge"

#: How much of a sanitised key survives into an ``item_id``, per half.
_ID_PREFIX_CHARS: Final = 24

#: How much of the digest of the whole pair is appended.
_ID_DIGEST_CHARS: Final = 16


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

    The readable prefix is not decoration. A run that dies between ``submit`` and
    ``fetch`` leaves a batch whose ids are all anyone has to work from until
    ``records.jsonl`` exists, and an operator reading ``batches.jsonl`` against the
    provider's console should be able to see which case is which.

    ``item_id`` is ``NonBlankEncodableText`` and is carried back byte-for-byte
    (ADR-0143 §9 chose it over ``Identifier`` for exactly that), so nothing here has
    to survive a normalisation.

    This names a question's **answer** item. Its judge item is this plus
    :data:`JUDGE_ITEM_SUFFIX`, so the two are joinable by stripping and are still
    telling apart in a provider's console, which shows ids and nothing else.

    Args:
        case_key: The case's key, as its corpus gives it.
        question_id: The question's id within that case.

    Returns:
        One id, unique to the pair, non-blank and ASCII.
    """
    readable = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in f"{case_key[:_ID_PREFIX_CHARS]}.{question_id[:_ID_PREFIX_CHARS]}"
    )
    digest = sha256(f"{case_key}\x00{question_id}".encode()).hexdigest()[:_ID_DIGEST_CHARS]
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
    """

    completer: BatchCompleter
    guard: SpendGuard
    run_id: str
    on_batch: BatchFile
    poll: PollPolicy
    announce: Callable[[str], None]


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
    session.announce(
        f"submitted {kind} batch {handle.batch_id} ({len(items)} items) under "
        f"issuer {handle.issuer}"
    )
    await _wait_for(session, handle, kind=kind)
    outcomes = await session.completer.fetch(handle)
    return {outcome.item_id: outcome for outcome in outcomes}


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

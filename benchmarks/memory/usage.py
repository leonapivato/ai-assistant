"""What a run's model calls cost, as far as this harness is able to observe it.

**Pilot-5 cost roughly double its estimate and its own artifacts could not say so**
(#1292). The overrun was reconstructed only by re-fetching the batch results from the
provider and summing per-item ``usage``, and the synchronous ingestion phase — the
observer and the reconciler, which together are most of what a run spends — left no
record of its size anywhere at all: not in ``records.jsonl``, not in the traces, not in
the manifest. This module is the ledger that closes the part of that gap the harness can
reach, and is explicit about the part it cannot.

**No token count crosses the seam this harness reads model answers through, and that is
the fact everything here is shaped around.** ``ModelProvider.complete`` returns a bare
:class:`~ai_assistant.core.types.Message` and ``BatchCompleter.fetch`` returns
:class:`~ai_assistant.core.types.BatchItemOutcome`, whose four fields are ``item_id``,
``kind``, ``message`` and ``failure``. Both implementations in ``models/`` hold the
vendor's usage figures and drop them one line before the value crosses the boundary —
``provider.py``'s ``return Message(role=Role.ASSISTANT, content=result.output)`` and
``batch.py``'s ``_succeeded_outcome``. Widening either type is a contract change, which
needs its own ratified ADR merged ahead of any implementation (golden rule 5, ADR-0015);
#1305 records the surfaces, quotes them, and is the input to that conversation.

The harness cannot route around it either. ``benchmarks/`` may not import a provider SDK
— ``tests/benchmarks/test_import_discipline.py`` parses every module here and fails on
one that does — so there is no second channel to read a token count from, and
``tiktoken`` is on the same forbidden list, so there is nothing to count with.

**So this ledger reports what it measured and refuses to dress anything else up as a
measurement.** What it measures is three figures the harness genuinely knows:

* **calls** — one per logical completion, the same currency
  :class:`~benchmarks.memory.spend.SpendGuard` charges and
  :func:`~benchmarks.memory.run.plan_run` counts, so a ledger row and a plan row are
  comparable. Split by *phase* and *route*, which is the split #1292 asks for and which
  the guard's single counter cannot give.
* **prompt_chars** — the characters sent, summed over the conversation handed to the
  seam. The same crude proxy ``QuestionRecord.context_chars`` already is, on the same
  ground: it costs nothing and a phase whose prompts are ten times another's is visible
  in it.
* **reply_chars** — the characters that came back.

**Characters are not tokens and nothing here converts between them.** A ratio would be
an estimate wearing a measurement's name, which is the exact failure #1292 exists to
end: the pilot-5 estimate that ran 2x low was built out of exactly that kind of
arithmetic. The token slots on :class:`UsageEntry` are therefore present and ``None``,
and :data:`TOKENS_UNAVAILABLE` says why on every artifact that carries one — an absent
number stays absent and is marked so. The day #1305's contract lands, those slots fill
in and nothing else about the artifact shape has to move.

**What chars are good for meanwhile** is apportionment. The one thing #1292 wants and
nobody has ever measured is the *share* ingestion takes, and a per-phase character
ledger plus a single re-fetched batch total answers that without anyone guessing: the
shares are measured, and only the one total is imported.

:data:`MEASURED_TOKENS` is the other half — per-question token figures measured exactly,
off previous pilots' batch results, so ``plan`` can report a token column that is
somebody's real measurement rather than a heuristic. It is deliberately not a model of
anything: it is a small table of observed numbers, each stamped with the run it came
from, and it says nothing at all about ingestion because nothing has ever measured that.
"""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003 — a pydantic field annotation is read at runtime
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from ai_assistant.core.types import Message

__all__ = [
    "MEASURED_TOKENS",
    "TOKENS_UNAVAILABLE",
    "BatchItemUsage",
    "MeasuredTokens",
    "UsageEntry",
    "UsageLedger",
    "UsagePhase",
    "UsageTally",
    "UsageTotals",
    "prompt_chars",
]


class UsagePhase(StrEnum):
    """Which of a run's four paid seams a model call was made on.

    The split :class:`~benchmarks.memory.spend.SpendGuard`'s single counter cannot give,
    and the one #1292 asks for. Every member corresponds to exactly one place a provider
    is wrapped, so a call's phase is fixed where the seam is built rather than inferred
    from what it looks like afterwards — a route is not enough to tell them apart,
    because ``observer_model`` and ``reconciler_model`` both fall back to
    ``default_model`` and a run that took both defaults would have three phases wearing
    one label.

    ``OBSERVATION`` and ``RECONCILIATION`` together are the *ingestion* share, which is
    the unknown #1292 exists to close: ingestion is synchronous under both run phases
    (``RunPhase``), dominates a run's spend, and has never been measured.
    """

    ANSWERING = "answering"
    """The seam a question is answered through — one call per question, or one batch item."""

    JUDGING = "judging"
    """The model judge. An instrument rather than part of the system under test, and
    frequently a different route, which is why it is counted apart."""

    OBSERVATION = "observation"
    """Distillation: episodes become beliefs. One call per window of captured turns, each
    carrying a whole window of transcript — so its call count and its size diverge
    further than any other phase's, and a ledger that recorded only calls would say the
    least about exactly the phase that costs the most."""

    RECONCILIATION = "reconciliation"
    """ADR-0159's conflict reconciler. Counted apart from observation although both are
    ingestion, because its call count is the one figure ``plan_run`` cannot tighten
    (``RunPlan.reconciler_calls`` reports a ceiling that pilot-5 put five times above the
    truth) — so a measured figure here is worth more than anywhere else in the plan."""


#: Why every token slot in this module is ``None``, recorded on the artifacts themselves.
#:
#: Stated on the artifact rather than left to a reader's knowledge of the tree, because
#: the artifact outlives the tree it was written from: someone reading a run directory in
#: six months has to be able to tell "this run made no token measurement" from "this run
#: measured zero tokens", and an absent key says neither.
TOKENS_UNAVAILABLE: Final = (
    "not measured: no token count crosses the ai_assistant model seam. "
    "ModelProvider.complete returns a bare Message and BatchItemOutcome carries only a "
    "Message, so the provider's usage figures are read inside models/ and dropped there "
    "(issue #1305). The character counts beside this are what the harness measured; they "
    "are not tokens, and no ratio between the two is applied anywhere."
)


def prompt_chars(messages: Sequence[Message]) -> int:
    """How many characters a conversation puts in front of the model.

    Every turn's content, summed. Roles and names are not counted: they are a handful of
    characters per turn and counting them would make the figure depend on a rendering
    this harness does not control, which is the sort of thing that quietly stops two
    runs being comparable.

    Args:
        messages: The conversation handed to the seam.

    Returns:
        The character count.
    """
    return sum(len(message.content) for message in messages)


class UsageEntry(BaseModel):
    """One ``(phase, route)`` bucket of a ledger, as it is written down.

    Attributes:
        phase: Which paid seam — a :class:`UsagePhase` value.
        route: The ``"provider:model"`` spec the calls went to. Recorded beside the phase
            rather than folded into it, because #1292 asks for run totals "by model, by
            phase" and a run may legitimately answer, distil and judge on three routes.
        calls: Logical completions, charged before the request exactly as
            :meth:`~benchmarks.memory.spend.SpendGuard.charge` charges them — so a call
            that failed outright is counted, and a call the retry policy repeated is
            counted once. That keeps this column in the same currency as
            :func:`~benchmarks.memory.run.plan_run`'s.
        prompt_chars: Characters sent, summed over every one of those calls. A failed
            call contributes its prompt, for the reason it contributes its charge: the
            request was made.
        reply_chars: Characters that came back. A failed call contributes nothing here,
            so ``reply_chars == 0`` against a positive ``calls`` is a phase that sent
            prompts and got no answers — which is information rather than a gap.
        input_tokens: Always ``None`` today. The slot is present so that the day
            #1305's contract lands the figure has somewhere to go and no consumer has to
            learn a new key; :data:`TOKENS_UNAVAILABLE` on the enclosing
            :class:`UsageTotals` says why it is empty.
        output_tokens: The same, for the reply.
    """

    model_config = ConfigDict(frozen=True)

    phase: str
    route: str
    calls: int = 0
    prompt_chars: int = 0
    reply_chars: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


class UsageTotals(BaseModel):
    """A ledger's readings at one scope, frozen for writing down.

    The shape carried by the manifest (the whole run), by each row of
    ``records.jsonl`` (one question's answering and judging), and — flattened by
    :meth:`flat`, since that object is a flat mapping — by each case's ingestion summary.

    Attributes:
        calls: Logical completions across every phase in this scope.
        prompt_chars: Characters sent across every phase.
        reply_chars: Characters returned across every phase.
        entries: One row per ``(phase, route)`` that made a call, in a stable order:
            phase first, then route. A phase that made no call has no row rather than a
            zero row, so "this scope never touched the reconciler" and "the reconciler
            was crossed and cost nothing" are distinguishable.
        tokens_measured: Always ``False`` today, and the field exists to *say* so. A
            reader holding one of these should not have to infer a negative from
            ``input_tokens`` being absent — the two readings of an absent number are the
            failure #1292 is about.
        tokens_unavailable: :data:`TOKENS_UNAVAILABLE` while ``tokens_measured`` is
            ``False``, and ``None`` once it is not.
    """

    model_config = ConfigDict(frozen=True)

    calls: int = 0
    prompt_chars: int = 0
    reply_chars: int = 0
    entries: tuple[UsageEntry, ...] = ()
    tokens_measured: bool = False
    tokens_unavailable: str | None = TOKENS_UNAVAILABLE

    def flat(self, *, prefix: str = "usage_") -> dict[str, int | str]:
        """The same readings as a flat mapping, for an artifact that cannot nest.

        A case's ingestion summary is denormalised onto every one of that case's record
        rows as a flat ``dict[str, int | float | str | list[str]]``
        (:attr:`~benchmarks.memory.records.QuestionRecord.ingestion`), so the ledger has
        to arrive there as scalars. **The routes are summed away and the phases are
        not**: the phases are what the ingestion share is a share *of*, and a run's
        observer and reconciler routes are each fixed for the whole run and already in
        the manifest, so nothing is lost by dropping them here.

        ``tokens_measured`` is rendered as the reason string rather than as a boolean,
        because this mapping's value type admits no ``bool`` and a ``bool`` smuggled
        through an ``int`` column would read as ``0`` — the one rendering of "not
        measured" that a reader could mistake for a measurement of zero.

        Args:
            prefix: What every key is prefixed with, so these cannot collide with the
                summary's own field names.

        Returns:
            The scalars: the three totals, the token marker, and three per-phase columns
            for each phase that made a call.
        """
        flattened: dict[str, int | str] = {
            f"{prefix}calls": self.calls,
            f"{prefix}prompt_chars": self.prompt_chars,
            f"{prefix}reply_chars": self.reply_chars,
            f"{prefix}tokens": (
                TOKENS_UNAVAILABLE if not self.tokens_measured else "measured; see entries"
            ),
        }
        for entry in self.entries:
            for column, value in (
                ("calls", entry.calls),
                ("prompt_chars", entry.prompt_chars),
                ("reply_chars", entry.reply_chars),
            ):
                key = f"{prefix}{entry.phase}_{column}"
                flattened[key] = int(flattened.get(key, 0) or 0) + value
        return flattened


@dataclass(slots=True)
class UsageTally:
    """Model-call usage accumulated over one scope — a run, a case, a question.

    A mutable accumulator with a frozen :meth:`snapshot`, the shape
    :class:`~benchmarks.memory.records._RetrievalFold` already has and for the same
    reason: what is recorded arrives one crossing at a time, and what is written down has
    to be one value.

    Attributes:
        buckets: ``(phase, route)`` mapped to its running ``[calls, prompt, reply]``.
            Private in effect — :meth:`record` is the only thing that writes it — but
            named plainly, because a benchmark's accumulator hiding its own arithmetic
            behind an underscore helps nobody debugging a number that looks wrong.
    """

    buckets: dict[tuple[str, str], list[int]] = field(default_factory=dict)

    def record(
        self,
        *,
        phase: UsagePhase,
        route: str,
        calls: int = 0,
        prompt: int = 0,
        reply: int = 0,
    ) -> None:
        """Add one crossing's readings to this scope.

        Every argument defaults to zero because the two halves of a call are recorded
        separately and deliberately: the prompt and the charge are recorded *before* the
        request, so a call that raises still contributes both, and the reply is recorded
        after it came back. That is the same asymmetry
        :class:`~benchmarks.memory.spend.SpendGuard` already has — "a guard that only
        counted successes would be defeated by exactly the failing run it exists to
        stop" — and it is why this takes three independent counts rather than one call's
        worth of everything.

        Args:
            phase: Which paid seam.
            route: The ``"provider:model"`` spec.
            calls: Logical completions to add, normally ``1`` or ``0``.
            prompt: Characters sent to add.
            reply: Characters returned to add.
        """
        bucket = self.buckets.setdefault((str(phase), route), [0, 0, 0])
        bucket[0] += calls
        bucket[1] += prompt
        bucket[2] += reply

    def snapshot(self) -> UsageTotals:
        """What this scope has accumulated so far, as a value.

        Returns:
            The totals. Ordered by phase then route, so two runs' artifacts diff
            cleanly and a test can assert on a sequence rather than on a set.
        """
        entries = tuple(
            UsageEntry(
                phase=phase,
                route=route,
                calls=counts[0],
                prompt_chars=counts[1],
                reply_chars=counts[2],
            )
            for (phase, route), counts in sorted(self.buckets.items())
        )
        return UsageTotals(
            calls=sum(entry.calls for entry in entries),
            prompt_chars=sum(entry.prompt_chars for entry in entries),
            reply_chars=sum(entry.reply_chars for entry in entries),
            entries=entries,
        )


@dataclass(slots=True)
class UsageLedger:
    """The run's whole account, plus whatever narrower scopes are open over it.

    **One ledger per run, held by the run's** :class:`~benchmarks.memory.spend.SpendGuard`,
    for the reason the guard itself is run-level: every seam draws on one account, and
    a per-seam ledger would leave nothing able to answer "what did this run cost".

    :meth:`attributing_to` is what makes a *narrower* answer possible. The driver opens a
    scope around the work it wants attributed — a case's ingestion, one question's answer
    and grading — and every crossing recorded while it is open lands in that scope as well
    as in the run's. Sound because a benchmark run is strictly sequential: one event loop,
    one case at a time, one question at a time, which is the same property
    :class:`~benchmarks.memory.records.TraceCursor` already relies on to read a walk to
    exhaustion.

    Scopes may nest, and an inner scope's crossings land in the outer one too. Nothing
    here nests today — a case scope covers ingestion only and closes before the question
    loop — and the containment rule is stated because the alternative (innermost wins)
    would silently drop a figure out of an outer total the day something did nest.

    Attributes:
        run: The whole run's tally, never closed.
        open_scopes: The narrower tallies currently receiving, innermost last.
    """

    run: UsageTally = field(default_factory=UsageTally)
    open_scopes: list[UsageTally] = field(default_factory=list)

    def record(
        self,
        *,
        phase: UsagePhase,
        route: str,
        calls: int = 0,
        prompt: int = 0,
        reply: int = 0,
    ) -> None:
        """Credit one crossing to the run and to every open scope.

        Args:
            phase: Which paid seam.
            route: The ``"provider:model"`` spec.
            calls: Logical completions to add.
            prompt: Characters sent to add.
            reply: Characters returned to add.
        """
        for tally in (self.run, *self.open_scopes):
            tally.record(phase=phase, route=route, calls=calls, prompt=prompt, reply=reply)

    @contextmanager
    def attributing_to(self, tally: UsageTally) -> Iterator[UsageTally]:
        """Also credit ``tally`` for everything recorded inside this block.

        Closed in a ``finally``, so a scope survives the one thing a paid run is most
        likely to end on: a :class:`~benchmarks.memory.spend.RunAbortedError` travelling
        past every handler that exists to keep one question's failure from ending the
        run. A scope left open by an abort would go on collecting another case's calls.

        Args:
            tally: Where to also record.

        Yields:
            The same tally, so a caller can open a scope and keep the accumulator in one
            expression.
        """
        self.open_scopes.append(tally)
        try:
            yield tally
        finally:
            self.open_scopes.remove(tally)


@dataclass(frozen=True, slots=True)
class BatchItemUsage:
    """What one settled batch item sent and got back, reported per item.

    The batched phase has no scope to be inside: every question is retrieved for, then
    all of them are submitted at once and read back hours later, so nothing is "current"
    when an answer arrives. Attribution there is therefore explicit —
    :func:`~benchmarks.memory.batch.submit_and_settle` reports one of these per submitted
    item, and the caller keys them back to questions by ``item_id`` exactly as ADR-0143
    §4 has it key outcomes.

    Attributes:
        item_id: The id the item was submitted under, byte-for-byte. A judge item still
            carries :data:`~benchmarks.memory.batch.JUDGE_ITEM_SUFFIX`; stripping it is
            the caller's, which is the same join it already does for the grading.
        phase: ``ANSWERING`` or ``JUDGING`` — which of the run's two batches this was.
        route: The ``"provider:model"`` spec the batch was submitted to.
        prompt_chars: Characters submitted for this item.
        reply_chars: Characters the outcome carried, and ``0`` for an item that expired,
            was cancelled or failed — which is the same reading a failed synchronous call
            gets, and is why a run's ungraded rows are visible here as prompts that bought
            nothing.
    """

    item_id: str
    phase: UsagePhase
    route: str
    prompt_chars: int
    reply_chars: int


class MeasuredTokens(BaseModel):
    """Per-question token figures a *previous* run measured, for the plan's token column.

    **Measured, not modelled**, and the distinction is the whole reason this table is
    small and stamped. Every figure here was read off a completed pilot's batch results —
    the provider's own per-item ``usage``, summed and divided by the question count — so
    it is somebody's real measurement of a real run rather than an estimate. #1292 asks
    for a plan column "grounded in measured per-question figures from prior runs rather
    than heuristics", and this is that grounding.

    **What it deliberately does not carry is ingestion.** Nothing has ever measured the
    observation and reconciliation share, which is the unknown #1292 exists to close, so
    the table states no number for it and :meth:`~benchmarks.memory.run.RunPlan` reports
    its token total as a floor rather than as an estimate. Inventing a figure here would
    reproduce exactly the arithmetic that put pilot-5's estimate 2x low.

    **The figures move with the prompt, which is why ``source`` is a field.** LoCoMo's
    answering cost went from 3,648 tok/q at a 15+15 retrieval budget (pilot-4) to 7,295
    effective at 30+10 under #1213's rendering (pilot-5), and LongMemEval's from 2,511 to
    11,254 — a 4.5x move on the same corpus with the same model. A token column carrying
    a bare number would be actively misleading a reader whose configuration differs; one
    carrying the run it was measured on lets them judge.

    Attributes:
        source: Which run measured these, and under what configuration. Printed beside
            the figures.
        answer_tokens: Input plus output tokens per answered question, measured.
        judge_tokens: The same for one judging call. Roughly flat across corpora — the
            judge reads a question, a reference answer and an answer, none of which
            scales with the retrieval budget.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    answer_tokens: int = Field(gt=0)
    judge_tokens: int = Field(gt=0)


#: Corpus key mapped to the per-question token figures a previous pilot measured on it.
#:
#: Pilot-5's, because those are the figures for the rendering the tree currently produces
#: (#1213) and the retrieval budget it currently ships; pilot-4's are named in
#: :class:`MeasuredTokens`'s docstring so the size of the move is visible rather than
#: only its result. Exact, from batch results, as #1292 records them.
#:
#: ``longmemeval-original`` is **absent rather than filled in from its cleaned sibling**.
#: The two are different files with different question sets, no pilot has run the
#: original, and a plan that copied one corpus's measurement onto another would be
#: precisely the estimate-as-measurement this module refuses. A corpus with no row gets a
#: plan that says it has none.
MEASURED_TOKENS: Final[Mapping[str, MeasuredTokens]] = {
    "locomo": MeasuredTokens(
        source="pilot-5, 30+10 retrieval budget, #1213 rendering",
        answer_tokens=7295,
        judge_tokens=200,
    ),
    "longmemeval": MeasuredTokens(
        source="pilot-5, 30+10 retrieval budget, #1213 rendering",
        answer_tokens=11254,
        judge_tokens=200,
    ),
}

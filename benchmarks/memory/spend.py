"""Stop a paid run on its own terms, rather than letting it die mid-loop.

**This exists because it has happened twice.** Pilot 2 and pilot 3 both ended partway
through on the same provider reply — a ``400 invalid_request_error`` whose body says the
account's credit balance is too low — and both left a run directory that is neither a
finished measurement nor a legible failure: a ``records.jsonl`` stopping at an arbitrary
question, a ``manifest.json`` describing a run that did not happen, and a traceback in a
terminal nobody kept. A benchmark whose artifacts cannot say "this run stopped, here,
for this reason" has to be re-run from the beginning to be believed, which is the
expensive half of the loss.

Two guards, and they answer different questions.

*The ceiling* is arithmetic the harness can do. :func:`~benchmarks.memory.run.plan_run`
already reports how many model calls a run would make before a provider is contacted, so
an operator holds a number; :class:`SpendGuard` is where that number becomes binding.
It counts calls rather than tokens or money on purpose: a call count is a figure the
harness *knows*, where tokens would be an estimate over prompts it has not built yet and
money would be a vendor's price list this tree has no business carrying. It is checked
before each call, so the bound is never exceeded rather than merely detected afterwards.

*The ledger* is the same seam asked a different question. The guard already sits on the
one path every model call the run builds goes down, so it is the only place that can say
what each of them cost — and until #1292 nothing did, which is how pilot-5 came in at
twice its estimate with artifacts unable to say where the money went. The guard therefore
carries a :class:`~benchmarks.memory.usage.UsageLedger` and records into it what it
already had in hand: the call it is charging, the route it is going to, the phase the
seam was built for, and the characters in and out. **That is not a token count and is not
converted into one** — the reasoning is
:mod:`benchmarks.memory.usage`'s, and it is the same reasoning the paragraph above gives
for the ceiling being in calls. Nothing about the bound changes: the ledger never
refuses, so a run's behaviour is identical whether or not anyone reads it.

**The unit is one *logical completion*, not one HTTP request, and the difference is a
choice.** The guard sits outside ``RetryingProvider``, so a call retried twice is charged
once. Two reasons, and the first is what makes the ceiling usable at all: ``plan_run``
counts logical calls, so a bound set by reading the plan is only meaningful in the same
currency — a ceiling that charged attempts would abort a run at an unpredictable
fraction of its plan, depending on how flaky the provider happened to be that hour. The
second is that attempts are the worse proxy for *spend* anyway: a provider bills a
completion it returned, and the attempts a retry replaces are the ones that failed. The
runaway a ceiling exists to stop is the number of questions, not the number of retries
within one — ``RetryPolicy.max_attempts`` already bounds those, per call, so that loop
cannot run away on its own.

*The credit signature* is the case the ceiling cannot predict, because it is a fact about
an account and not about this run — another process spending the same balance, a
top-up that did not land, a price that moved. **The harness cannot read the balance**:
nothing in the ``ModelProvider`` seam exposes one, and adding a vendor billing call would
be a provider SDK in a tree golden rule 4 keeps them out of. What is available is the
error the provider returns when it happens, so that is what is matched — narrowly, on
the phrases the two vendors in play use, and documented as the heuristic it is.

**Both raise :class:`RunAbortedError`, and it is deliberately not a ``ModelError``.**
``answer_question`` catches ``ModelError`` per question and records it as one failed
answer, which is right for a transient fault and catastrophic here: an abort wearing that
class would be swallowed 1,600 times and the run would complete, reporting a corpus-wide
collapse in accuracy that was really a billing event. Raising outside that hierarchy is
what makes the stop a stop.

**A false positive is the cheap direction and a false negative is the status quo.** If
the signature matches something that was not a credit exhaustion, the run stops early
with its records intact and its manifest saying why — recoverable, and visible. If it
matches nothing, the harness behaves exactly as it did before this module existed. So
the match is allowed to be a heuristic; what it may not be is silent, which is why the
reason reaches the manifest rather than only a log line.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ModelError
from benchmarks.memory.usage import UsageLedger, prompt_chars

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import Message
    from benchmarks.memory.usage import UsagePhase

__all__ = [
    "CREDIT_EXHAUSTION_SIGNATURES",
    "RunAbortedError",
    "SpendGuard",
    "is_credit_exhaustion",
]

#: Substrings that identify a provider refusing a call for want of funds.
#:
#: Lowercased and matched against the error's text. The list is short and vendor-named
#: rather than general: ``anthropic`` returns "Your credit balance is too low to access
#: the API" as a ``400``, and ``openai`` returns ``insufficient_quota`` with "You
#: exceeded your current quota". A looser pattern — "billing", "payment", "quota" alone —
#: would start catching rate limits, which are transient and must stay retryable.
#:
#: **The provider's error text is untrusted content and this is the one thing done with
#: it.** Nothing here records it: ``answer.py`` and ``grade.py`` both keep only the error's
#: class name for that reason, and this module keeps to the same rule — the match is read,
#: the decision is recorded, the text is dropped.
CREDIT_EXHAUSTION_SIGNATURES: Final = (
    "credit balance",
    "insufficient_quota",
    "exceeded your current quota",
    "billing_hard_limit_reached",
)


class RunAbortedError(Exception):
    """The run stopped itself, before the work it was asked to do was finished.

    Outside the ``AssistantError`` hierarchy on purpose, and outside ``ModelError``
    especially: ``answer_question`` catches ``ModelError`` per question and records it as
    one failed answer, so an abort that were one would be swallowed once per question and
    the run would finish, reporting a corpus-wide accuracy collapse that was really a
    billing event. This is not a failure *of* a model call; it is a decision about the
    run, and it travels past every handler that exists to keep one question's failure
    from ending the run.

    Attributes:
        reason: Why the run stopped, in a form fit for the manifest — one sentence, no
            provider text, and specific enough that a reader of the artifacts alone can
            tell an exhausted ceiling from an exhausted account.
    """

    def __init__(self, reason: str) -> None:
        """Record why the run stopped.

        Args:
            reason: The manifest-bound explanation.
        """
        super().__init__(reason)
        self.reason = reason


def is_credit_exhaustion(error: ModelError) -> bool:
    """Whether ``error`` is a provider refusing the call for want of funds.

    A text match, because it is the only evidence available at this seam: the failure
    arrives as a ``400``, which ``models.provider._classify_status`` maps to a bare
    ``ModelError`` — correctly, since any other 4xx is a malformed request and retrying
    is pointless — and no field of it distinguishes "your request was wrong" from "your
    account is empty".

    The class is deliberately *not* narrowed to a bare ``ModelError``: a vendor is free
    to report the same condition under another status, and a signature that only fired
    for one classification would go quiet on the day it moved. The signatures carry the
    specificity instead.

    Args:
        error: The failure a provider raised.

    Returns:
        ``True`` if the text carries one of :data:`CREDIT_EXHAUSTION_SIGNATURES`.
    """
    text = str(error).lower()
    return any(signature in text for signature in CREDIT_EXHAUSTION_SIGNATURES)


@dataclass(slots=True)
class SpendGuard:
    """One run's model-call budget, shared by every seam the run builds.

    Run-level rather than per-seam, which is the whole point: ingestion, answering and
    judging draw on one account, and three separate budgets would each be under their own
    bound while the account went to zero. One instance is created per
    :func:`~benchmarks.memory.run.execute_run` and handed to every provider it wires.

    **It covers every seam the run builds, and that is the exact extent of it.** A caller
    may inject the answering seam, the distillation seam or the grader, and only the
    first of the three is a ``ModelProvider`` this can wrap. An injected ``Observer`` or
    ``Grader`` holds its own provider behind a surface with no accessor, so a run given
    one spends outside this budget — see
    :func:`~benchmarks.memory.wiring.build_harness` and
    :func:`~benchmarks.memory.run.build_grader`. The gap is bounded by who may inject:
    ``refuse_ineligible_scored_run`` clause 5 refuses every injected seam outright, so a
    *scored* run is covered entirely, and a smoke run's artifacts are already not a
    measurement. It is stated rather than closed because closing it would mean either
    refusing the ``FakeObserver`` every test injects — which makes no call at all — or
    widening the ``Observer`` contract for the harness's convenience, and a benchmark
    does not get to do that.

    **Calls, not tokens and not money, and one logical completion is one call.** The call
    count is a figure the harness knows and ``plan_run`` already prints, so a ceiling in
    the same currency is one an operator can set by reading the plan; the module
    docstring argues why a retried call is charged once. Tokens would be an estimate over
    prompts not yet built, and money would put a vendor's price list in this tree.

    **The ledger rides along because this is the only seam that can carry it.** ``calls``
    below is one number for a whole run, which is what a ceiling needs and is exactly
    what #1292 found insufficient for reading a bill: it cannot say whether the spend was
    ingestion or answering. :attr:`usage` is the same crossings recorded with the phase
    and route attached. It bounds nothing and refuses nothing.

    Attributes:
        limit: The most model calls this run may make, or ``None`` for no ceiling —
            which is the default, so the behaviour of every existing caller is unchanged
            and the guard is a counter until somebody asks for a bound.
        calls: How many have been charged — one per logical completion asked for,
            counted before the request rather than after the reply, so a call that fails
            outright still spends. A guard that only counted successes would be defeated
            by exactly the failing run it exists to stop, and a bound checked afterwards
            is one the run has already crossed.
        usage: What each of those calls sent and got back, by phase and route. Created
            per guard and so per run, never shared, and never consulted by ``charge``:
            the ceiling's arithmetic is unchanged by anything recorded here.

            **It is not a total of the run's spend and does not claim to be.** It covers
            exactly what ``calls`` covers — every seam the run *builds* — so an injected
            ``Observer`` or ``Grader`` is outside it for the reason stated above, and a
            batch's items are recorded by
            :func:`~benchmarks.memory.batch.submit_and_settle` rather than here, since a
            batch does not cross :meth:`wrap`.
    """

    limit: int | None = None
    calls: int = 0
    usage: UsageLedger = field(default_factory=UsageLedger)

    def __post_init__(self) -> None:
        """Refuse a bound that is not a count.

        ``bool`` is excluded although it is an ``int`` subclass, for the reason
        ``Harness.__post_init__`` excludes it from its own bounds: ``True`` type-checks
        as an ``int`` and would cap a whole paid run at one call.

        Raises:
            TypeError: If ``limit`` is not an integer or ``None``, ``bool`` included.
            ValueError: If ``limit`` is negative. Zero is legal and permits no call at
                all, which is a meaningful thing to ask for — it is what "plan only"
                looks like from inside a run.
        """
        if self.limit is None:
            return
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            msg = f"limit must be an integer or None, got {self.limit!r}"
            raise TypeError(msg)
        if self.limit < 0:
            msg = f"limit must not be negative, got {self.limit}"
            raise ValueError(msg)

    def charge(self) -> None:
        """Account for one model call about to be made.

        Checked *before* the call rather than after, so the ceiling is a bound the run
        never crosses rather than one it notices having crossed. A run stopped here has
        made exactly ``limit`` calls.

        Raises:
            RunAbortedError: If the ceiling is already reached.
        """
        if self.limit is not None and self.calls >= self.limit:
            msg = (
                f"the run-level ceiling of {self.limit} model calls was reached; "
                f"stopped before making another"
            )
            raise RunAbortedError(msg)
        self.calls += 1

    def charge_many(self, count: int) -> None:
        """Account for ``count`` model calls about to be made as one submission.

        **All or nothing, because a batch is.** ``BatchCompleter.submit`` refuses or
        accepts the whole set and never the well-formed subset (ADR-0143 §3), so a
        guard that charged item by item until it met the ceiling would leave the run
        having spent N against a batch it never sent. Checked once for the whole
        count instead: either the submission fits under the bound or the run stops
        without making it.

        The currency is unchanged — one logical completion, one charge — so a
        ceiling read off :func:`~benchmarks.memory.run.plan_run` means the same
        number of answers whichever phase spends it. That is the property that lets
        ``--max-model-calls`` be set from the plan without knowing which phase will
        run.

        Args:
            count: How many calls the submission carries. Zero is legal and charges
                nothing — a judge batch is empty whenever every answer was settled
                by abstention, and that is a real run rather than an error.

        Raises:
            ValueError: If ``count`` is negative.
            RunAbortedError: If the ceiling cannot cover the whole submission. The
                run has made exactly ``calls`` calls and sent nothing further.
        """
        if count < 0:
            msg = f"count must not be negative, got {count}"
            raise ValueError(msg)
        if self.limit is not None and self.calls + count > self.limit:
            msg = (
                f"a batch of {count} model calls would take the run past its ceiling "
                f"of {self.limit} ({self.calls} already made); stopped before "
                f"submitting it"
            )
            raise RunAbortedError(msg)
        self.calls += count

    def wrap(self, provider: ModelProvider, *, phase: UsagePhase, route: str) -> ModelProvider:
        """Put ``provider`` behind this guard, labelled with what it is.

        **Both labels are required rather than defaulted, and that is the point of
        them.** A default would let a newly wrapped seam acquire whatever phase happened
        to be first in the enum, and a mislabelled ledger row is worse than a missing
        one: it is a number that looks like a measurement of the wrong thing. The
        wrapping sites are few and each of them knows exactly which seam it is building.

        Args:
            provider: The seam to guard.
            phase: Which of the run's paid seams this provider *is*. Fixed here, where
                the seam is built, because nothing downstream can tell an observation
                call from a reconciliation one — the two routes both fall back to
                ``default_model``.
            route: The ``"provider:model"`` spec this seam was built on, for the
                ledger's "by model" split.

        Returns:
            A provider that charges this guard for every call, records what that call
            sent and got back, and converts a credit-exhaustion refusal into a
            :class:`RunAbortedError`.
        """
        return _GuardedProvider(provider, self, phase, route)


@dataclass(slots=True)
class _GuardedProvider:
    """A ``ModelProvider`` that spends a :class:`SpendGuard` and stops the run on empty.

    A wrapper rather than a count kept by the driver, because the driver does not make
    every call: distillation's are made inside ``ObservationStage``, several layers down,
    and a figure the driver modelled would be a model of the run rather than the run. It
    sits *outside* ``RetryingProvider`` where the harness builds one, so a retried call is
    charged once — which is what ``plan_run`` counts and therefore what a ceiling read off
    the plan means. The module docstring holds the argument for that placement and names
    what it gives up.

    **That same placement is what makes the ledger's rows mean anything.** A recorder
    inside the retry would count attempts, so a flaky hour would look like an expensive
    one; here a phase's ``calls`` column and ``plan_run``'s figure for that phase are the
    same currency and can be read against each other.

    Attributes:
        _inner: The seam being wrapped.
        _guard: The run's ceiling and ledger.
        _phase: Which paid seam this is, fixed by whoever built it.
        _route: The ``"provider:model"`` spec it was built on.
    """

    _inner: ModelProvider
    _guard: SpendGuard
    _phase: UsagePhase
    _route: str

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Charge the guard, record what is being sent, delegate, record what came back.

        **The two halves are recorded separately, and the split is the same one the
        charge already makes.** The call and its prompt land before the request, so a
        call that raises still contributes both — it was made, and it is billed. The
        reply lands only if there is one, so a phase showing prompts against no replies
        is a phase whose calls all failed, which is a reading worth having rather than a
        hole.

        Args:
            messages: Conversation history, as the Protocol requires.
            model: Optional route override, relayed untouched. Recorded as the route
                where it is given, because it is where the call actually went; the
                harness's own seams do not pass one, so in practice this is the route
                :meth:`SpendGuard.wrap` was told about.

        Returns:
            The reply.

        Raises:
            RunAbortedError: If the ceiling is reached, or if the provider refused the call
                for want of funds.
            ModelError: Anything else the provider raised, re-raised unchanged — a
                per-question failure is the driver's to record, not this wrapper's to
                reinterpret.
        """
        self._guard.charge()
        route = model if model is not None else self._route
        self._guard.usage.record(
            phase=self._phase, route=route, calls=1, prompt=prompt_chars(messages)
        )
        try:
            reply = await self._inner.complete(messages, model=model)
        except ModelError as error:
            if is_credit_exhaustion(error):
                msg = (
                    f"the provider refused a call for want of credit after "
                    f"{self._guard.calls} model calls; stopped rather than recording "
                    f"the rest of the run as failed answers"
                )
                raise RunAbortedError(msg) from error
            raise
        self._guard.usage.record(phase=self._phase, route=route, reply=len(reply.content))
        return reply

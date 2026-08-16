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

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ai_assistant.core.errors import ModelError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.protocols import ModelProvider
    from ai_assistant.core.types import Message

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

    **Calls, not tokens and not money.** The call count is a figure the harness knows and
    ``plan_run`` already prints, so a ceiling in the same currency is one an operator can
    set by reading the plan. Tokens would be an estimate over prompts not yet built, and
    money would put a vendor's price list in this tree.

    Attributes:
        limit: The most model calls this run may make, or ``None`` for no ceiling —
            which is the default, so the behaviour of every existing caller is unchanged
            and the guard is a counter until somebody asks for a bound.
        calls: How many have been charged. Counted at the attempt rather than at the
            reply, so a call that fails still spends: it may well have been billed, and a
            guard that only counted successes would be defeated by exactly the failing
            run it exists to stop.
    """

    limit: int | None = None
    calls: int = 0

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

    def wrap(self, provider: ModelProvider) -> ModelProvider:
        """Put ``provider`` behind this guard.

        Args:
            provider: The seam to guard.

        Returns:
            A provider that charges this guard for every call and converts a
            credit-exhaustion refusal into a :class:`RunAbortedError`.
        """
        return _GuardedProvider(provider, self)


@dataclass(slots=True)
class _GuardedProvider:
    """A ``ModelProvider`` that spends a :class:`SpendGuard` and stops the run on empty.

    A wrapper rather than a count kept by the driver, because the driver does not make
    every call: distillation's are made inside ``ObservationStage``, several layers down,
    and a figure the driver modelled would be a model of the run rather than the run. It
    sits *outside* ``RetryingProvider`` where the harness builds one, so a retried call is
    charged once — which is what ``plan_run`` counts and therefore what a ceiling read off
    the plan means.
    """

    _inner: ModelProvider
    _guard: SpendGuard

    async def complete(self, messages: Sequence[Message], *, model: str | None = None) -> Message:
        """Charge the guard, then delegate.

        Args:
            messages: Conversation history, as the Protocol requires.
            model: Optional route override, relayed untouched.

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
        try:
            return await self._inner.complete(messages, model=model)
        except ModelError as error:
            if is_credit_exhaustion(error):
                msg = (
                    f"the provider refused a call for want of credit after "
                    f"{self._guard.calls} model calls; stopped rather than recording "
                    f"the rest of the run as failed answers"
                )
                raise RunAbortedError(msg) from error
            raise

"""A canonical, dependency-free :class:`~ai_assistant.core.protocols.ContextProvider` fake.

The shared test double for the ``ContextProvider`` contract, so a subsystem that
consumes situational context (orchestration, planning, ...) can test against a
real, contract-correct provider *without importing the context subsystem's
internals* (CLAUDE.md golden rule 1) and without standing up its sources. It
lives in ``ai_assistant.testing`` so it is importable from any test while staying
out of production code paths (``lint-imports`` forbids production modules from
importing it).

Unlike ``AssemblingContextProvider`` it composes nothing: it returns a context
fixed at construction, so a consumer's test can state the situational "right now"
it is exercising as data. Beyond the contract it records how many times it was
asked, and can be configured to fail, so the caller's degradation path is
testable without hand-rolling a raising mock; only the behaviour pinned by the
shared ``ContextProvider`` conformance suite is part of the contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ai_assistant.core.errors import ContextError
from ai_assistant.core.types import CurrentContext, TimeOfDay

# A weekday mid-morning, inside a 9-17 working window: the unremarkable default,
# so a test that does not care about the situation does not have to describe one.
# Wednesday 2026-06-03, 10:00 UTC.
_DEFAULT_CONTEXT = CurrentContext(
    now=datetime(2026, 6, 3, 10, 0, tzinfo=UTC),
    time_of_day=TimeOfDay.MORNING,
    is_weekend=False,
    within_working_hours=True,
)


class FakeContextProvider:
    """A ``ContextProvider`` test double that returns a context fixed up front.

    Structurally implements
    :class:`~ai_assistant.core.protocols.ContextProvider`. Every :meth:`assemble`
    increments :attr:`call_count` and returns a copy of the configured context, or
    raises the configured failure.
    """

    def __init__(
        self, context: CurrentContext | None = None, *, failure: str | None = None
    ) -> None:
        """Create the fake provider.

        Args:
            context: The context every :meth:`assemble` returns. Defaults to a
                weekday mid-morning inside working hours.
            failure: If given, :meth:`assemble` raises ``ContextError`` with this
                message instead of returning. Lets a consumer exercise its
                context-step failure path against the shared fake rather than a
                bespoke raising mock.

                A message rather than an exception instance, deliberately.
                ``ContextError`` is the subsystem's whole failure boundary —
                ``AssemblingContextProvider`` degrades every other exception
                per-source rather than propagating it, and nothing subclasses
                ``ContextError`` — so an instance parameter would add no
                expressiveness while making it possible to configure the canonical
                fake to raise outside the contract. It also keeps each call's
                exception independent; a stored instance re-raised would accumulate
                a traceback across calls.

        Raises:
            ValueError: If both ``context`` and ``failure`` are given (they
                describe incompatible outcomes, and silently letting one win would
                hide a mis-wired test), or if ``context.now`` carries a timezone
                whose offset is indeterminate.
        """
        if context is not None and failure is not None:
            msg = "pass either context or failure, not both"
            raise ValueError(msg)
        if (
            context is not None
            and context.now.tzinfo is not None
            and context.now.utcoffset() is None
        ):
            # A *naive* `now` is not this case — revalidation below normalises it to
            # UTC, as constructing the model would have. This is the narrower one:
            # `CurrentContext` requires only `tzinfo is not None`, which a custom
            # tzinfo returning `None` from `utcoffset()` satisfies while still being
            # indeterminate. Revalidation cannot fix that, so the fake would fail the
            # tz-aware assertion in its own conformance suite and downstream aware
            # comparisons would raise. Caught here so the fake cannot be the thing
            # that breaks the contract; tightening `CurrentContext` itself is a
            # `core/` change, left as a follow-up rather than widened into this lane.
            msg = "context.now must have a determinate UTC offset"
            raise ValueError(msg)
        # Snapshotted on ingress as well as egress: the context is fixed *at
        # construction*, so a caller that keeps its reference and mutates it later
        # must not be able to change what assemble returns. Snapshotting the default
        # too keeps the module-level constant from being reachable at all.
        #
        # Re-validated rather than `model_copy`d: `CurrentContext` does not validate
        # on assignment, so a caller can hand over a model it mutated into an
        # invalid state (a naive `now`, most likely) — and the fake would then fail
        # the tz-aware assertion in its own conformance suite. Validating here
        # rejects it at the point the mistake was made, and normalises a naive
        # `now` to UTC exactly as constructing the model would have.
        source = context if context is not None else _DEFAULT_CONTEXT
        self._context = CurrentContext.model_validate(source.model_dump())
        self._failure = failure
        self.call_count = 0

    async def assemble(self) -> CurrentContext:
        """Record the call and return the configured context, or raise the failure.

        The returned context is a deep copy, so a caller that mutates it cannot
        reach the fake's stored context and change what a later call sees.

        Raises:
            ContextError: Carrying the ``failure`` message passed at construction,
                if one was given. A fresh instance per call.
        """
        self.call_count += 1
        if self._failure is not None:
            raise ContextError(self._failure)
        return self._context.model_copy(deep=True)

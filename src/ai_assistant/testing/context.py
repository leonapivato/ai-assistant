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
        self, context: CurrentContext | None = None, *, failure: Exception | None = None
    ) -> None:
        """Create the fake provider.

        Args:
            context: The context every :meth:`assemble` returns. Defaults to a
                weekday mid-morning inside working hours.
            failure: If given, :meth:`assemble` raises this instead of returning.
                Lets a consumer exercise its context-step failure path — the
                Protocol allows ``assemble`` to raise ``ContextError`` — against
                the shared fake rather than a bespoke mock.

        Raises:
            ValueError: If both ``context`` and ``failure`` are given. The two
                describe incompatible outcomes, and silently letting one win
                would hide a mis-wired test.
        """
        if context is not None and failure is not None:
            msg = "pass either context or failure, not both"
            raise ValueError(msg)
        # Deep-copied on ingress as well as egress: the context is fixed *at
        # construction*, so a caller that keeps its reference and mutates it later
        # must not be able to change what assemble returns. Copying the default
        # too keeps the module-level constant from being reachable at all.
        source = context if context is not None else _DEFAULT_CONTEXT
        self._context = source.model_copy(deep=True)
        self._failure = failure
        self.call_count = 0

    async def assemble(self) -> CurrentContext:
        """Record the call and return the configured context, or raise the failure.

        The returned context is a deep copy, so a caller that mutates it cannot
        reach the fake's stored context and change what a later call sees.

        Raises:
            Exception: The ``failure`` passed at construction, if any.
        """
        self.call_count += 1
        if self._failure is not None:
            raise self._failure
        return self._context.model_copy(deep=True)

"""The canonical fake for :class:`~ai_assistant.core.protocols.CoverageAnswers` (ADR-0270 §1).

**The proposal writer's face onto condition 6**, and the narrow one: one member, no
way to rule on a request, no way to reach an ``Authorization`` and no way to read a
goal's quotes for itself. A writer handed this cannot name ``decide``, ``resolve``,
``record`` or ``for_action``, which is the static guarantee ADR-0097 §3's split buys
and which ``mypy --strict`` is what enforces.

**It computes nothing** (ADR-0266 §7). Condition 6 has *"One implementation, in
``permissions``"*, and a fake that evaluated the two routes would be a second place
the rule lives — the first conforming implementation to read it differently would be
right in one of them. So the answer is **configured**: a test that wants *"the policy
said the coverage was met, over this quote"* says so, rather than arranging a request,
a declaration, a member and a quote that happen to make the production comparison
answer that way today.

**Two obligations override the configuration**, because a fake that could be
configured into violating its own conformance suite would be a trap for the consumer
it certifies (``FakeMemoryPolicy``'s own three are the precedent).

* **A quote rides back only where the evidence route could have decided one** — where
  the answer is met **and** ``coverage`` carries a ``MONEY`` member, that being the
  one kind the evidence route can meet (ADR-0266 §7). ADR-0270 §2's presence rule is
  *"absent in every other case"*, and it is the half
  :class:`~ai_assistant.core.types.CoverageAnswer` cannot hold for itself: the model
  carries no coverage to test itself against.
* **An unmet answer carries no quote.** The model refuses that outright, so a fake
  configured with a quote and ``met`` false would raise rather than answer — the
  first override covers this one as well, and it is stated because it is the rule a
  reader looks for.

**The quote crosses this boundary detached, in both directions**, which is
``FakeGoalQuotes``' rule one seam later and for the same reason: an amount rewritten
through a returned object is a ceiling proved against a figure no provider ever
quoted, and a path-(i) writer records this value on the row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from ai_assistant.core.errors import AuthorizationError
from ai_assistant.core.types import BoundKind, CoverageAnswer
from ai_assistant.testing.cancellation import SuspendableResource

if TYPE_CHECKING:
    from ai_assistant.core.types import ActionQuote, ActionRequest, CoverageMember
    from ai_assistant.testing.cancellation import LoopSuspension, ResourceLog


@final
class FakeCoverageAnswers:
    """A ``CoverageAnswers`` test double that returns a configured answer (ADR-0270 §1).

    Structurally implements :class:`~ai_assistant.core.protocols.CoverageAnswers`.
    Every call is recorded to :attr:`calls`, so a test can assert what its subject
    actually asked about — which for the proposal path is the whole question: the
    writer is obliged to put condition 6 through this seam and to re-implement no
    conjunct of it.
    """

    def __init__(self, *, met: bool = True, quote: ActionQuote | None = None) -> None:
        """Create the seam.

        Args:
            met: Whether it answers that the coverage satisfies condition 6.
            quote: The governing quote a met answer over a ``MONEY``-carrying
                coverage rides back with (ADR-0270 §2). ``None`` — the default —
                is the answer for every coverage the evidence route decides
                nothing about, which is every coverage carrying no ``MONEY``
                member.
        """
        self._met = met
        self._quote = None if quote is None else quote.model_copy(deep=True)
        self._calls: list[tuple[ActionRequest, tuple[CoverageMember, ...]]] = []
        self._resource = SuspendableResource()
        self._failure: Exception | None = None

    @property
    def calls(self) -> tuple[tuple[ActionRequest, tuple[CoverageMember, ...]], ...]:
        """Every ``(request, coverage)`` pair this seam was asked about, in order.

        **Detached on record**, so a caller that rewrites what it passed afterwards
        cannot move what a test reads back here.
        """
        return tuple(self._calls)

    @property
    def call_count(self) -> int:
        """How many times :meth:`coverage_met` has been called.

        ADR-0270 §3's *"no answer is cached, carried to a dispatch or read by any
        later comparison"* is a rule about the caller as much as the answerer, and a
        seam that cannot be counted cannot falsify it.
        """
        return len(self._calls)

    def answer(self, *, met: bool, quote: ActionQuote | None = None) -> None:
        """Reconfigure what the next calls answer.

        Args:
            met: Whether condition 6 holds.
            quote: The governing quote, subject to the class docstring's first
                override.
        """
        self._met = met
        self._quote = None if quote is None else quote.model_copy(deep=True)

    def fail_coverage_met(self, error: Exception | None = None) -> None:
        """Arm every subsequent :meth:`coverage_met` to raise a store fault.

        **The branch ADR-0270 §4's fault clause is stated over.** The member
        propagates ``GoalQuotes.for_action``'s
        :class:`~ai_assistant.core.errors.AuthorizationError` rather than converting
        it into a met answer, an unmet one, or an empty tuple of quotes; a component
        that asked then writes no row and the one call is confirmed under ADR-0148
        §3's route (a).

        Args:
            error: The fault to raise. An
                :class:`~ai_assistant.core.errors.AuthorizationError` by default,
                which is the one class this member raises.
        """
        self._failure = (
            error
            if error is not None
            else AuthorizationError("fake: the goal's quotes could not be read")
        )

    async def coverage_met(
        self, request: ActionRequest, coverage: tuple[CoverageMember, ...]
    ) -> CoverageAnswer:
        """The configured answer, with §2's presence rule held over it.

        Args:
            request: The action a row would be proposed for. **Read for nothing**:
                this fake evaluates no conjunct of condition 6 and reads no field of
                it, recording it so a test can assert what was asked.
            coverage: The coverage that row would carry. Read for **one** thing —
                whether it carries a ``MONEY`` member, which is what decides whether
                a quote may ride back at all (ADR-0270 §2).

        Returns:
            The configured answer, carrying the configured quote exactly where
            ``met`` is true and ``coverage`` carries a ``MONEY`` member.

        Raises:
            Exception: Whatever :meth:`fail_coverage_met` armed.
        """
        members = tuple(coverage)
        self._calls.append(
            (
                request.model_copy(deep=True),
                tuple(member.model_copy(deep=True) for member in members),
            )
        )
        if self._failure is not None:
            raise self._failure
        async with self._resource.held():
            priced = any(member.kind is BoundKind.MONEY for member in members)
            quoted = self._quote if self._met and priced else None
            return CoverageAnswer(
                met=self._met,
                quoted=None if quoted is None else quoted.model_copy(deep=True),
            )

    def suspend_next_operation(self) -> LoopSuspension:
        """Hold the next call that enters the modelled resource open inside it."""
        return self._resource.suspend_next()

    @property
    def resource_log(self) -> ResourceLog:
        """When each call was inside the modelled resource (ADR-0060's case reads it)."""
        return self._resource.log


__all__ = ["FakeCoverageAnswers"]

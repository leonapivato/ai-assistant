"""A canonical, rule-free :class:`~ai_assistant.core.protocols.MemoryPolicy` fake.

The shared test double for the ``MemoryPolicy`` contract, so a subsystem that
depends on the propose/dispose write path (``learning``, ``orchestration``, ...)
can drive a policy to any outcome it needs to exercise *without importing the
memory subsystem's internals* (CLAUDE.md golden rule 1) and without depending on
``DefaultMemoryPolicy``'s particular rules — which are an implementation choice
and expected to change (see ``TODO.md`` item 2).

That independence is the point. A test that wants "the policy said MERGE" should
say so directly, rather than reverse-engineering a proposal that happens to make
the production policy merge today and something else tomorrow.

Beyond the contract it records every call to :attr:`calls`, so a test can assert
what its subject actually proposed. Only the behaviour pinned by the shared
``MemoryPolicy`` conformance suite is part of the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from ai_assistant.core.types import (
    DataTier,
    MemoryDecision,
    MemoryDecisionKind,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_assistant.core.types import MemoryRecord, MemoryUpdateProposal

_DEFAULT_TTL = timedelta(days=1)


@dataclass(frozen=True)
class PolicyCall:
    """One recorded call to a :class:`FakeMemoryPolicy`.

    Attributes:
        proposal: The proposal passed to ``decide``, as an independent snapshot.
        conflicts: The conflicting records passed alongside it, likewise
            snapshotted. Both are deep-copied on record, so neither reassigning
            the caller's list nor mutating a record inside it can reach what was
            recorded.
    """

    proposal: MemoryUpdateProposal
    conflicts: tuple[MemoryRecord, ...]


class FakeMemoryPolicy:
    """A ``MemoryPolicy`` test double that returns a configured outcome.

    Structurally implements
    :class:`~ai_assistant.core.protocols.MemoryPolicy`. Every call is appended to
    :attr:`calls` and answered with :attr:`kind`, so a test picks the branch it
    wants to exercise instead of constructing a proposal that provokes it.

    Two contract obligations override the configured kind, because a fake that
    could be configured into violating its own conformance suite would be a trap:

    * **Secret-tier proposals are never committed** (ADR-0004 §3) — they return
      ``ASK_USER`` whatever ``kind`` says.
    * **``MERGE`` needs a target.** With no conflicts to merge into there is no
      representable merge decision, so it falls back to ``ACCEPT``.

    Both are visible in the returned :attr:`~MemoryDecision.reason`, so a
    surprised test can see what happened rather than silently passing.
    """

    def __init__(
        self,
        kind: MemoryDecisionKind = MemoryDecisionKind.ACCEPT,
        *,
        ttl: timedelta = _DEFAULT_TTL,
    ) -> None:
        """Create the fake policy.

        Args:
            kind: The ruling to return for every proposal, subject to the two
                overrides in the class docstring.
            ttl: The retention window attached to ``STORE_TEMPORARY`` decisions;
                must be positive, since a non-positive window would produce an
                already-expired record.

        Raises:
            ValueError: If ``ttl`` is not positive — the ``MemoryDecision``
                validator would reject it later, so a fake configured this way
                could only fail at ``decide`` time, far from the mistake.
                Checked whatever ``kind`` is, including kinds that carry no ttl:
                :attr:`kind` is public and reassignable, so a ttl validated only
                when it looked relevant would go unchecked the moment a test
                flipped the fake to ``STORE_TEMPORARY``.
        """
        if ttl <= timedelta(0):
            msg = f"ttl must be positive, got {ttl}"
            raise ValueError(msg)
        self.kind = kind
        self._ttl = ttl
        self.calls: list[PolicyCall] = []

    async def decide(
        self,
        proposal: MemoryUpdateProposal,
        *,
        conflicts: Sequence[MemoryRecord],
    ) -> MemoryDecision:
        """Record the call and return the configured decision."""
        self.calls.append(
            PolicyCall(
                proposal=proposal.model_copy(deep=True),
                conflicts=tuple(c.model_copy(deep=True) for c in conflicts),
            )
        )

        if proposal.sensitivity is DataTier.SECRET:
            return MemoryDecision(
                kind=MemoryDecisionKind.ASK_USER,
                reason="fake: secret-tier data is never committed",
            )

        kind = self.kind
        if kind is MemoryDecisionKind.MERGE and not conflicts:
            return MemoryDecision(
                kind=MemoryDecisionKind.ACCEPT,
                reason="fake: no conflict to merge into, accepted instead",
            )

        if kind is MemoryDecisionKind.MERGE:
            return MemoryDecision(
                kind=kind,
                merge_into=conflicts[0].id,
                reason="fake: configured decision",
            )

        if kind is MemoryDecisionKind.STORE_TEMPORARY:
            return MemoryDecision(kind=kind, ttl=self._ttl, reason="fake: configured decision")

        return MemoryDecision(kind=kind, reason="fake: configured decision")

    @property
    def call_count(self) -> int:
        """How many times ``decide`` has been called."""
        return len(self.calls)

    @property
    def last_proposal(self) -> MemoryUpdateProposal:
        """The recorded snapshot of the most recent call's proposal.

        Equal to what the caller passed, but not the same object — compare it by
        value, not identity.

        Raises:
            IndexError: If ``decide`` has not been called.
        """
        return self.calls[-1].proposal
